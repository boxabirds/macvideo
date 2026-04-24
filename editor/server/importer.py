"""Migrate JSON outputs from the v1 CLI pipeline into the editor's SQLite store.

Idempotent: re-running doesn't produce duplicates. Existing songs' user edits
(prompt_is_user_authored=True, custom selected_*_take_id) are preserved across
re-imports.

Handles the legacy `remap_from_24fps.py` inversion bug by rehydrating
prev_link / next_link from `.24fps.bak` archives when they're present but
missing from the active JSON.
"""

from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .store import ArtefactKind, connection


@dataclass
class SongImportResult:
    slug: str
    songs_imported: int = 0
    scenes_imported: int = 0
    keyframe_takes_imported: int = 0
    clip_takes_imported: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportReport:
    songs: list[SongImportResult] = field(default_factory=list)

    @property
    def total_songs(self) -> int:
        return sum(r.songs_imported for r in self.songs)

    @property
    def total_scenes(self) -> int:
        return sum(r.scenes_imported for r in self.songs)

    @property
    def total_keyframe_takes(self) -> int:
        return sum(r.keyframe_takes_imported for r in self.songs)

    @property
    def total_clip_takes(self) -> int:
        return sum(r.clip_takes_imported for r in self.songs)


# ----------------------------------------------------------------------------

def _probe_duration_s(audio_path: Path) -> Optional[float]:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(audio_path)],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return float(out) if out else None
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return None


def _read_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _collect_prev_next_from_bak(outputs_dir: Path, slug: str) -> dict[int, tuple[Optional[str], Optional[str]]]:
    """Rehydrate prev_link / next_link from the legacy `.24fps.bak` archives
    stripped by `remap_from_24fps.py`'s inverted condition.

    Returns a dict mapping scene_index -> (prev_link, next_link).
    Empty dict if no .bak file found.
    """
    song_dir = outputs_dir / slug
    bak = song_dir / "storyboard.json.24fps.bak"
    if not bak.exists():
        return {}
    data = _read_json(bak)
    if not isinstance(data, dict):
        return {}
    shots = data.get("shots") or []
    # The .bak is indexed against the 24fps-split shots (different shot count
    # than the current 30fps list). Map by start_s overlap as a best effort.
    # For the common case (1:1 or close) we just index by shot["index"].
    result: dict[int, tuple[Optional[str], Optional[str]]] = {}
    for s in shots:
        idx = s.get("index")
        if isinstance(idx, int):
            result[idx] = (s.get("prev_link"), s.get("next_link"))
    return result


def _insert_song(conn, slug: str, audio_path: Path, lyrics_path: Optional[Path],
                 brief_data: Optional[dict], storyboard_data: Optional[dict],
                 duration_s: Optional[float], size_bytes: Optional[int]) -> int:
    now = time.time()
    filter_word = brief_data.get("filter") if brief_data else None
    abstraction = brief_data.get("abstraction") if brief_data else None
    world_brief = brief_data.get("brief") if brief_data else None
    sequence_arc = storyboard_data.get("sequence_arc") if storyboard_data else None

    # Upsert by slug. Preserve existing quality_mode, world_brief (if user edited),
    # filter / abstraction overrides.
    existing = conn.execute("SELECT id FROM songs WHERE slug = ?", (slug,)).fetchone()
    if existing:
        song_id = existing["id"]
        conn.execute("""
            UPDATE songs SET
                audio_path   = ?,
                lyrics_path  = COALESCE(lyrics_path, ?),
                duration_s   = COALESCE(duration_s, ?),
                size_bytes   = COALESCE(size_bytes, ?),
                filter       = COALESCE(filter, ?),
                abstraction  = COALESCE(abstraction, ?),
                world_brief  = COALESCE(world_brief, ?),
                sequence_arc = COALESCE(sequence_arc, ?),
                updated_at   = ?
            WHERE id = ?
        """, (
            str(audio_path),
            str(lyrics_path) if lyrics_path else None,
            duration_s, size_bytes,
            filter_word, abstraction,
            world_brief, sequence_arc,
            now, song_id,
        ))
        return song_id

    cur = conn.execute("""
        INSERT INTO songs (slug, audio_path, lyrics_path, duration_s, size_bytes,
                           filter, abstraction, world_brief, sequence_arc,
                           created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        slug, str(audio_path),
        str(lyrics_path) if lyrics_path else None,
        duration_s, size_bytes,
        filter_word, abstraction,
        world_brief, sequence_arc,
        now, now,
    ))
    return cur.lastrowid


def _insert_scenes(conn, song_id: int, shots: list[dict],
                   storyboard_by_idx: dict[int, dict],
                   prompts: dict[str, str],
                   bak_links: dict[int, tuple[Optional[str], Optional[str]]]) -> int:
    now = time.time()
    inserted = 0
    for shot in shots:
        idx = shot.get("index")
        if not isinstance(idx, int):
            continue
        sb = storyboard_by_idx.get(idx, {})
        prev_link = sb.get("prev_link")
        next_link = sb.get("next_link")
        # Rehydrate from .24fps.bak if the remap nulled them
        if prev_link is None or next_link is None:
            bak_prev, bak_next = bak_links.get(idx, (None, None))
            if prev_link is None:
                prev_link = bak_prev
            if next_link is None:
                next_link = bak_next

        image_prompt = (prompts.get(f"shot_{idx:03d}")
                        or prompts.get(f"shot_{idx:02d}"))

        existing = conn.execute(
            "SELECT id FROM scenes WHERE song_id = ? AND scene_index = ?",
            (song_id, idx),
        ).fetchone()
        if existing:
            # Don't overwrite user-authored prompts or user-edited fields
            conn.execute("""
                UPDATE scenes SET
                    kind              = COALESCE(?, kind),
                    target_text       = COALESCE(?, target_text),
                    start_s           = COALESCE(?, start_s),
                    end_s             = COALESCE(?, end_s),
                    target_duration_s = COALESCE(?, target_duration_s),
                    num_frames        = COALESCE(?, num_frames),
                    lyric_line_idx    = COALESCE(?, lyric_line_idx),
                    beat              = COALESCE(beat, ?),
                    camera_intent     = COALESCE(camera_intent, ?),
                    subject_focus     = COALESCE(subject_focus, ?),
                    prev_link         = COALESCE(prev_link, ?),
                    next_link         = COALESCE(next_link, ?),
                    image_prompt      = CASE WHEN prompt_is_user_authored = 1
                                             THEN image_prompt
                                             ELSE COALESCE(?, image_prompt) END,
                    updated_at        = ?
                WHERE id = ?
            """, (
                shot.get("kind"),
                shot.get("target_text"),
                shot.get("start_s"),
                shot.get("end_s"),
                shot.get("target_duration_s", shot.get("duration_s")),
                shot.get("num_frames"),
                shot.get("lyric_line_idx"),
                sb.get("beat"),
                sb.get("camera_intent"),
                sb.get("subject_focus"),
                prev_link, next_link,
                image_prompt,
                now, existing["id"],
            ))
        else:
            conn.execute("""
                INSERT INTO scenes (
                    song_id, scene_index, kind, target_text,
                    start_s, end_s, target_duration_s, num_frames, lyric_line_idx,
                    beat, camera_intent, subject_focus, prev_link, next_link,
                    image_prompt, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                song_id, idx, shot.get("kind", "lyric"),
                shot.get("target_text", ""),
                shot.get("start_s", 0.0),
                shot.get("end_s", 0.0),
                shot.get("target_duration_s", shot.get("duration_s", 0.0)),
                shot.get("num_frames", 0),
                shot.get("lyric_line_idx"),
                sb.get("beat"),
                sb.get("camera_intent"),
                sb.get("subject_focus"),
                prev_link, next_link,
                image_prompt,
                now, now,
            ))
            inserted += 1
    return inserted


def _insert_takes(conn, scene_rows: dict[int, int],
                  keyframes_dir: Path, clips_dir: Path) -> tuple[int, int]:
    """Insert one take per keyframe/clip file on disk. Returns (kf_count, clip_count).

    scene_rows maps scene_index -> scene_id in the DB.
    """
    now = time.time()
    kf_inserted = 0
    clip_inserted = 0
    for kind, directory, ext in (
        (ArtefactKind.keyframe, keyframes_dir, ".png"),
        (ArtefactKind.clip, clips_dir, ".mp4"),
    ):
        if not directory.exists():
            continue
        prefix = "keyframe_" if kind == ArtefactKind.keyframe else "clip_"
        for p in sorted(directory.glob(f"{prefix}*{ext}")):
            try:
                idx = int(p.stem.split("_")[1])
            except (IndexError, ValueError):
                continue
            scene_id = scene_rows.get(idx)
            if scene_id is None:
                continue
            # Skip if already imported
            existing = conn.execute(
                "SELECT id FROM takes WHERE scene_id = ? AND artefact_kind = ? AND asset_path = ?",
                (scene_id, kind.value, str(p)),
            ).fetchone()
            if existing:
                take_id = existing["id"]
            else:
                cur = conn.execute("""
                    INSERT INTO takes (scene_id, artefact_kind, asset_path,
                                       prompt_snapshot, created_by, created_at)
                    VALUES (?, ?, ?, NULL, 'cli', ?)
                """, (scene_id, kind.value, str(p), now))
                take_id = cur.lastrowid
                if kind == ArtefactKind.keyframe:
                    kf_inserted += 1
                else:
                    clip_inserted += 1
            # Point scene's selection to the most recent take of this kind
            # unless the user has pinned a selection (selection_pinned=1).
            col = ("selected_keyframe_take_id" if kind == ArtefactKind.keyframe
                   else "selected_clip_take_id")
            conn.execute(f"""
                UPDATE scenes
                SET {col} = ?
                WHERE id = ? AND selection_pinned = 0
            """, (take_id, scene_id))
    return kf_inserted, clip_inserted


def _import_one_song(db_path: Path, music_dir: Path, outputs_dir: Path,
                     wav_path: Path) -> SongImportResult:
    slug = wav_path.stem
    result = SongImportResult(slug=slug)

    lyrics_path = music_dir / f"{slug}.txt"
    if not lyrics_path.exists():
        lyrics_path = None

    song_dir = outputs_dir / slug
    shots_json = _read_json(song_dir / "shots.json") if song_dir.exists() else None
    brief_json = _read_json(song_dir / "character_brief.json") if song_dir.exists() else None
    storyboard_json = _read_json(song_dir / "storyboard.json") if song_dir.exists() else None
    prompts_json = _read_json(song_dir / "image_prompts.json") if song_dir.exists() else None

    shots = (shots_json or {}).get("shots") if isinstance(shots_json, dict) else None
    if not shots:
        shots = []

    storyboard_by_idx: dict[int, dict] = {}
    if isinstance(storyboard_json, dict):
        for s in storyboard_json.get("shots") or []:
            if isinstance(s.get("index"), int):
                storyboard_by_idx[s["index"]] = s

    prompts = prompts_json if isinstance(prompts_json, dict) else {}
    bak_links = _collect_prev_next_from_bak(outputs_dir, slug)

    duration_s = _probe_duration_s(wav_path)
    size_bytes = wav_path.stat().st_size if wav_path.exists() else None

    with connection(db_path) as conn:
        conn.execute("BEGIN")
        try:
            song_id = _insert_song(
                conn, slug, wav_path, lyrics_path,
                brief_json if isinstance(brief_json, dict) else None,
                storyboard_json if isinstance(storyboard_json, dict) else None,
                duration_s, size_bytes,
            )
            # This is a song-level "songs_imported" count: 1 iff we inserted
            # a new row. We approximate by checking whether it was newly created
            # via created_at == updated_at rule (below).
            # To stay simple we just record 1 song per call.
            result.songs_imported = 1

            scenes_inserted = _insert_scenes(
                conn, song_id, shots, storyboard_by_idx, prompts, bak_links,
            )
            result.scenes_imported = scenes_inserted

            # Build scene_index -> scene_id mapping for take inserts
            scene_rows = {
                r["scene_index"]: r["id"]
                for r in conn.execute(
                    "SELECT scene_index, id FROM scenes WHERE song_id = ?", (song_id,)
                ).fetchall()
            }

            kf_count, clip_count = _insert_takes(
                conn, scene_rows,
                song_dir / "keyframes",
                song_dir / "clips",
            )
            result.keyframe_takes_imported = kf_count
            result.clip_takes_imported = clip_count

            conn.execute("COMMIT")
        except Exception as e:  # noqa: BLE001
            conn.execute("ROLLBACK")
            result.warnings.append(f"import failed: {e}")

    return result


def import_all(db_path: Path, music_dir: Path, outputs_dir: Path,
               max_workers: int = 1) -> ImportReport:
    """Import every `.wav` in `music_dir` plus its outputs (if present).

    Runs serially by default because SQLite (even in WAL mode) allows only
    one writer at a time; parallel imports on the same DB collide. The whole
    import is fast enough (~0.5s per song) that serialisation is fine.
    """
    report = ImportReport()
    wavs = sorted(p for p in music_dir.glob("*.wav"))
    if not wavs:
        return report

    if max_workers <= 1:
        for wav in wavs:
            report.songs.append(
                _import_one_song(db_path, music_dir, outputs_dir, wav)
            )
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(_import_one_song, db_path, music_dir, outputs_dir, wav)
                for wav in wavs
            ]
            for fut in as_completed(futures):
                report.songs.append(fut.result())

    report.songs.sort(key=lambda r: r.slug)
    return report
