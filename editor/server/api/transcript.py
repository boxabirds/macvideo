"""Word-level transcript correction routes."""

from __future__ import annotations

import json
import re
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .common import get_db


router = APIRouter()

_TOKEN_RE = re.compile(r"\S+")


class TranscriptWord(BaseModel):
    id: int
    word_index: int
    text: str
    start_s: float
    end_s: float
    original_text: str
    original_start_s: float
    original_end_s: float
    correction_id: int | None
    warning: str | None


class TranscriptResponse(BaseModel):
    scene_index: int
    target_text: str
    words: list[TranscriptWord]


class CorrectionBody(BaseModel):
    start_word_index: int = Field(ge=0)
    end_word_index: int = Field(ge=0)
    text: str


def _coded_error(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


def _fetch_scene(conn, slug: str, idx: int):
    row = conn.execute("""
        SELECT s.*, g.id AS song_id, g.slug AS song_slug
        FROM scenes s
        JOIN songs g ON g.id = s.song_id
        WHERE g.slug = ? AND s.scene_index = ?
    """, (slug, idx)).fetchone()
    if row is None:
        raise _coded_error(404, "scene_not_found", f"scene {idx} of song '{slug}' not found")
    return row


def _tokenize(text: str) -> list[str]:
    return [m.group(0) for m in _TOKEN_RE.finditer(text or "")]


def _seed_words(conn, scene) -> None:
    existing = conn.execute(
        "SELECT COUNT(*) FROM transcript_words WHERE scene_id = ?",
        (scene["id"],),
    ).fetchone()[0]
    if existing:
        return
    tokens = _tokenize(scene["target_text"])
    if not tokens:
        return
    now = time.time()
    start = float(scene["start_s"])
    end = float(scene["end_s"])
    duration = max(0.001, end - start)
    step = duration / len(tokens)
    for i, tok in enumerate(tokens):
        word_start = start + step * i
        word_end = end if i == len(tokens) - 1 else start + step * (i + 1)
        conn.execute("""
            INSERT INTO transcript_words (
                scene_id, word_index, text, start_s, end_s,
                original_text, original_start_s, original_end_s,
                correction_id, warning, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
        """, (
            scene["id"], i, tok, word_start, word_end,
            tok, word_start, word_end, now, now,
        ))


def _words(conn, scene_id: int):
    return conn.execute(
        "SELECT * FROM transcript_words WHERE scene_id = ? ORDER BY word_index",
        (scene_id,),
    ).fetchall()


def _word_payload(row) -> dict:
    return {
        "id": row["id"],
        "word_index": row["word_index"],
        "text": row["text"],
        "start_s": row["start_s"],
        "end_s": row["end_s"],
        "original_text": row["original_text"],
        "original_start_s": row["original_start_s"],
        "original_end_s": row["original_end_s"],
        "correction_id": row["correction_id"],
        "warning": row["warning"],
    }


def _sync_scene_text(conn, scene_id: int) -> str:
    words = _words(conn, scene_id)
    text = " ".join(w["text"] for w in words)
    conn.execute(
        "UPDATE scenes SET target_text = ?, updated_at = ? WHERE id = ?",
        (text, time.time(), scene_id),
    )
    return text


def _response(conn, scene) -> TranscriptResponse:
    _seed_words(conn, scene)
    text = _sync_scene_text(conn, scene["id"])
    return TranscriptResponse(
        scene_index=scene["scene_index"],
        target_text=text,
        words=[TranscriptWord(**_word_payload(w)) for w in _words(conn, scene["id"])],
    )


def _replace_interval(conn, *, scene, start_idx: int, end_idx: int, replacement_text: str,
                      correction_id: int | None) -> None:
    words = _words(conn, scene["id"])
    selected = [w for w in words if start_idx <= w["word_index"] <= end_idx]
    if not selected:
        raise _coded_error(422, "invalid_word_selection", "selection contains no words")

    replacement = _tokenize(replacement_text)
    interval_start = float(selected[0]["start_s"])
    interval_end = float(selected[-1]["end_s"])
    now = time.time()

    kept_before = [w for w in words if w["word_index"] < start_idx]
    kept_after = [w for w in words if w["word_index"] > end_idx]
    rebuilt: list[dict] = []
    rebuilt.extend(_word_payload(w) for w in kept_before)

    if replacement:
        step = max(0.001, (interval_end - interval_start) / len(replacement))
        for i, tok in enumerate(replacement):
            word_start = interval_start + step * i
            word_end = interval_end if i == len(replacement) - 1 else interval_start + step * (i + 1)
            source = selected[min(i, len(selected) - 1)]
            rebuilt.append({
                "text": tok,
                "start_s": word_start,
                "end_s": word_end,
                "original_text": source["original_text"],
                "original_start_s": source["original_start_s"],
                "original_end_s": source["original_end_s"],
                "correction_id": correction_id,
                "warning": None,
            })

    rebuilt.extend(_word_payload(w) for w in kept_after)

    conn.execute("DELETE FROM transcript_words WHERE scene_id = ?", (scene["id"],))
    for i, w in enumerate(rebuilt):
        conn.execute("""
            INSERT INTO transcript_words (
                scene_id, word_index, text, start_s, end_s,
                original_text, original_start_s, original_end_s,
                correction_id, warning, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            scene["id"], i, w["text"], w["start_s"], w["end_s"],
            w["original_text"], w["original_start_s"], w["original_end_s"],
            w["correction_id"], w["warning"], now, now,
        ))
    _sync_scene_text(conn, scene["id"])


def _apply_correction(conn, *, scene, start_idx: int, end_idx: int, text: str) -> int | None:
    _seed_words(conn, scene)
    words = _words(conn, scene["id"])
    if not words:
        raise _coded_error(422, "no_transcript_words", "scene has no transcript words")
    if start_idx > end_idx or start_idx < 0 or end_idx >= len(words):
        raise _coded_error(422, "invalid_word_selection", "selection must stay within the scene")

    selected = [w for w in words if start_idx <= w["word_index"] <= end_idx]
    original_text = " ".join(w["text"] for w in selected)
    if original_text == text:
        return None

    now = time.time()
    cur = conn.execute("""
        INSERT INTO transcript_corrections (
            song_id, scene_id, original_words_json, corrected_words_json,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'applied', ?, ?)
    """, (
        scene["song_id"], scene["id"],
        json.dumps([_word_payload(w) for w in selected]),
        json.dumps({"start_word_index": start_idx, "end_word_index": end_idx, "text": text}),
        now, now,
    ))
    correction_id = cur.lastrowid
    _replace_interval(
        conn, scene=scene, start_idx=start_idx, end_idx=end_idx,
        replacement_text=text, correction_id=correction_id,
    )
    return correction_id


@router.get("/songs/{slug}/scenes/{idx}/transcript", response_model=TranscriptResponse)
def get_scene_transcript(slug: str, idx: int, conn=Depends(get_db)):
    return _response(conn, _fetch_scene(conn, slug, idx))


@router.post("/songs/{slug}/scenes/{idx}/transcript/corrections", response_model=TranscriptResponse)
def apply_scene_correction(slug: str, idx: int, body: CorrectionBody, conn=Depends(get_db)):
    scene = _fetch_scene(conn, slug, idx)
    _apply_correction(
        conn, scene=scene, start_idx=body.start_word_index,
        end_idx=body.end_word_index, text=body.text,
    )
    return _response(conn, scene)


def _latest_correction(conn, slug: str, status: Literal["applied", "undone"]):
    row = conn.execute("""
        SELECT tc.*, s.scene_index, g.slug
        FROM transcript_corrections tc
        JOIN songs g ON g.id = tc.song_id
        JOIN scenes s ON s.id = tc.scene_id
        WHERE g.slug = ? AND tc.status = ?
        ORDER BY tc.updated_at DESC, tc.id DESC
        LIMIT 1
    """, (slug, status)).fetchone()
    return row


def _restore_words(conn, *, scene_id: int, words_payload: list[dict], correction_id: int | None) -> None:
    now = time.time()
    conn.execute("DELETE FROM transcript_words WHERE scene_id = ?", (scene_id,))
    for i, w in enumerate(words_payload):
        conn.execute("""
            INSERT INTO transcript_words (
                scene_id, word_index, text, start_s, end_s,
                original_text, original_start_s, original_end_s,
                correction_id, warning, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            scene_id, i, w["text"], w["start_s"], w["end_s"],
            w.get("original_text", w["text"]),
            w.get("original_start_s", w["start_s"]),
            w.get("original_end_s", w["end_s"]),
            w.get("correction_id", correction_id), w.get("warning"), now, now,
        ))
    _sync_scene_text(conn, scene_id)


@router.post("/songs/{slug}/transcript/undo", response_model=TranscriptResponse)
def undo_latest_correction(slug: str, conn=Depends(get_db)):
    corr = _latest_correction(conn, slug, "applied")
    if corr is None:
        raise _coded_error(409, "no_undo_available", "no applied correction to undo")
    original = json.loads(corr["original_words_json"])
    all_words = [_word_payload(w) for w in _words(conn, corr["scene_id"])]
    corrected_ids = {w["id"] for w in all_words if w["correction_id"] == corr["id"]}
    if corrected_ids:
        first = next(i for i, w in enumerate(all_words) if w["correction_id"] == corr["id"])
        last = max(i for i, w in enumerate(all_words) if w["correction_id"] == corr["id"])
        rebuilt = all_words[:first] + original + all_words[last + 1:]
    else:
        rebuilt = original + all_words
    _restore_words(conn, scene_id=corr["scene_id"], words_payload=rebuilt, correction_id=None)
    conn.execute(
        "UPDATE transcript_corrections SET status = 'undone', updated_at = ? WHERE id = ?",
        (time.time(), corr["id"]),
    )
    scene = _fetch_scene(conn, slug, corr["scene_index"])
    return _response(conn, scene)


@router.post("/songs/{slug}/transcript/redo", response_model=TranscriptResponse)
def redo_latest_correction(slug: str, conn=Depends(get_db)):
    corr = _latest_correction(conn, slug, "undone")
    if corr is None:
        raise _coded_error(409, "no_redo_available", "no undone correction to redo")
    scene = _fetch_scene(conn, slug, corr["scene_index"])
    payload = json.loads(corr["corrected_words_json"])
    _replace_interval(
        conn, scene=scene,
        start_idx=payload["start_word_index"],
        end_idx=payload["end_word_index"],
        replacement_text=payload["text"],
        correction_id=corr["id"],
    )
    conn.execute(
        "UPDATE transcript_corrections SET status = 'applied', updated_at = ? WHERE id = ?",
        (time.time(), corr["id"]),
    )
    return _response(conn, scene)


@router.post("/songs/{slug}/scenes/{idx}/transcript/corrections/{correction_id}/revert", response_model=TranscriptResponse)
def revert_correction(slug: str, idx: int, correction_id: int, conn=Depends(get_db)):
    scene = _fetch_scene(conn, slug, idx)
    corr = conn.execute(
        "SELECT * FROM transcript_corrections WHERE id = ? AND scene_id = ?",
        (correction_id, scene["id"]),
    ).fetchone()
    if corr is None:
        raise _coded_error(404, "correction_not_found", "correction not found")
    original = json.loads(corr["original_words_json"])
    all_words = [_word_payload(w) for w in _words(conn, scene["id"])]
    matching = [i for i, w in enumerate(all_words) if w["correction_id"] == correction_id]
    if not matching:
        raise _coded_error(404, "correction_not_found", "correction is not applied")
    rebuilt = all_words[:matching[0]] + original + all_words[matching[-1] + 1:]
    _restore_words(conn, scene_id=scene["id"], words_payload=rebuilt, correction_id=None)
    conn.execute(
        "UPDATE transcript_corrections SET status = 'undone', updated_at = ? WHERE id = ?",
        (time.time(), correction_id),
    )
    return _response(conn, scene)
