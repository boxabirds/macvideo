"""Test-only endpoints, mounted only when EDITOR_TEST_ENDPOINTS=1.

Used by the e2e harness to manipulate filesystem state from inside the
browser test (e.g. inject a lyrics file mid-test to exercise the
recover-from-failed flow). NOT mounted in production.
"""

from __future__ import annotations

import os
import json
import time
import wave
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config as _cfg
from ..importer import import_all


router = APIRouter()


class WriteLyricsBody(BaseModel):
    slug: str
    text: str


def is_enabled() -> bool:
    return os.environ.get("EDITOR_TEST_ENDPOINTS") == "1"


@router.post("/test-only/write-lyrics")
def write_lyrics(body: WriteLyricsBody):
    """Write music/<slug>.txt and re-import so the song picks up the file."""
    if not is_enabled():
        raise HTTPException(status_code=404, detail="not found")
    target = Path(_cfg.MUSIC_DIR) / f"{body.slug}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.text)
    import_all(_cfg.DB_PATH, _cfg.MUSIC_DIR, _cfg.OUTPUTS_DIR)
    return {"ok": True, "path": str(target)}


class ResetSongBody(BaseModel):
    slug: str


@router.post("/test-only/reset-song")
def reset_song(body: ResetSongBody):
    """Restore a song to its fresh state: delete lyrics file, scenes, regen
    runs, and the run dir. Used by Story 14's audio-transcribe spec to clean
    up after itself so subsequent tests on the same fixture see a fresh
    song."""
    if not is_enabled():
        raise HTTPException(status_code=404, detail="not found")
    lyrics = Path(_cfg.MUSIC_DIR) / f"{body.slug}.txt"
    lyrics.unlink(missing_ok=True)
    run_dir = Path(_cfg.OUTPUTS_DIR) / body.slug
    if run_dir.exists():
        import shutil
        shutil.rmtree(run_dir, ignore_errors=True)
    from ..store import connection
    with connection(_cfg.DB_PATH) as c:
        row = c.execute("SELECT id FROM songs WHERE slug = ?", (body.slug,)).fetchone()
        if row:
            sid = row["id"]
            c.execute("DELETE FROM scenes WHERE song_id = ?", (sid,))
            c.execute("DELETE FROM regen_runs WHERE song_id = ?", (sid,))
            c.execute(
                """
                UPDATE songs
                SET filter = NULL,
                    abstraction = NULL,
                    world_brief = NULL,
                    sequence_arc = NULL
                WHERE id = ?
                """,
                (sid,),
            )
    return {"ok": True}


class EnvOverrideBody(BaseModel):
    set: dict[str, str | None]


_ALLOWED_ENV_KEYS = {
    "EDITOR_FAKE_GEN_KEYFRAMES",
    "EDITOR_FAKE_RENDER_CLIPS",
    "EDITOR_FAKE_WHISPERX_ALIGN",
    "EDITOR_FAKE_MAKE_SHOTS",
    "EDITOR_FAKE_DEMUCS",
    "EDITOR_FAKE_WHISPERX_TRANSCRIBE",
    "EDITOR_GENERATION_PROVIDER",
    "EDITOR_GENERATION_MODEL",
    "EDITOR_LYRIC_LINE_PROVIDER",
    "EDITOR_FAKE_LYRIC_LINE_MODE",
    "EDITOR_RENDER_PROVIDER",
    "GEMINI_API_KEY",
}


@router.post("/test-only/env")
def set_env(body: EnvOverrideBody):
    """Temporarily adjust backend process env for browser tests only."""
    if not is_enabled():
        raise HTTPException(status_code=404, detail="not found")
    disallowed = sorted(set(body.set) - _ALLOWED_ENV_KEYS)
    if disallowed:
        raise HTTPException(status_code=422, detail={
            "reason": "disallowed test env override",
            "keys": disallowed,
        })
    for key, value in body.set.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return {"ok": True, "updated": sorted(body.set)}


class WorkflowFixtureBody(BaseModel):
    slug: str = "workflow-e2e"
    filter: str | None = "charcoal"
    abstraction: int | None = 0
    world_brief: str | None = "world"
    sequence_arc: str | None = "arc"
    include_prompts: bool = True
    include_takes: bool = True
    include_failed_runs: bool = True


def _write_fixture_wav(path: Path) -> None:
    framerate = 8000
    frames = int(2 * framerate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(framerate)
        wav.writeframes(b"\x00\x00" * frames)


@router.post("/test-only/workflow-fixture")
def create_workflow_fixture(body: WorkflowFixtureBody):
    """Create an isolated browser fixture for centralized workflow-state tests."""
    if not is_enabled():
        raise HTTPException(status_code=404, detail="not found")
    from ..store import connection

    wav_path = Path(_cfg.MUSIC_DIR) / f"{body.slug}.wav"
    _write_fixture_wav(wav_path)
    now = time.time()
    with connection(_cfg.DB_PATH) as c:
        existing = c.execute("SELECT id FROM songs WHERE slug = ?", (body.slug,)).fetchone()
        if existing:
            c.execute("DELETE FROM songs WHERE id = ?", (existing["id"],))
        cur = c.execute(
            """
            INSERT INTO songs (
                slug, audio_path, duration_s, size_bytes, filter, abstraction,
                quality_mode, world_brief, sequence_arc, created_at, updated_at
            ) VALUES (?, ?, 2, ?, ?, ?, 'draft', ?, ?, ?, ?)
            """,
            (
                body.slug, str(wav_path), wav_path.stat().st_size,
                body.filter, body.abstraction,
                body.world_brief, body.sequence_arc, now, now,
            ),
        )
        song_id = cur.lastrowid
        for idx in (1, 2):
            scene = c.execute(
                """
                INSERT INTO scenes (
                    song_id, scene_index, kind, target_text, start_s, end_s,
                    target_duration_s, num_frames, beat, image_prompt,
                    dirty_flags, created_at, updated_at
                ) VALUES (?, ?, 'lyric', ?, ?, ?, 1, 24, ?, ?, ?, ?, ?)
                """,
                (
                    song_id, idx, f"line {idx}", idx - 1, idx,
                    f"beat {idx}" if body.sequence_arc else None,
                    f"prompt {idx}" if body.include_prompts else None,
                    json.dumps(["keyframe_stale", "clip_stale"]) if idx == 1 else "[]",
                    now, now,
                ),
            )
            scene_id = scene.lastrowid
            if body.include_takes:
                keyframe = c.execute(
                    "INSERT INTO takes (scene_id, artefact_kind, asset_path, created_by, created_at) "
                    "VALUES (?, 'keyframe', ?, 'editor', ?)",
                    (scene_id, f"{body.slug}/keyframe-{idx}.png", now),
                )
                clip = c.execute(
                    "INSERT INTO takes (scene_id, artefact_kind, asset_path, created_by, created_at) "
                    "VALUES (?, 'clip', ?, 'editor', ?)",
                    (scene_id, f"{body.slug}/clip-{idx}.mp4", now),
                )
                c.execute(
                    "UPDATE scenes SET selected_keyframe_take_id = ?, selected_clip_take_id = ? WHERE id = ?",
                    (keyframe.lastrowid, clip.lastrowid, scene_id),
                )
        if body.include_failed_runs:
            c.execute(
                """
                INSERT INTO regen_runs (
                    scope, song_id, status, error, started_at, ended_at, created_at
                ) VALUES ('stage_world_brief', ?, 'failed', 'world generation failed', ?, ?, ?)
                """,
                (song_id, now - 20, now - 10, now - 10),
            )
            c.execute(
                """
                INSERT INTO regen_runs (
                    scope, song_id, status, phase, progress_pct, started_at, created_at
                ) VALUES ('stage_audio_transcribe', ?, 'running', 'transcribing', 50, ?, ?)
                """,
                (song_id, now - 5, now),
            )
    return {"ok": True, "slug": body.slug}
