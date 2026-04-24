"""After a subprocess writes new files to a song's run_dir, pull them back
into the SQLite store as new `takes` rows. Also refresh song-level fields
(world_brief, sequence_arc, filter/abstraction → mirrored on takes).

This is the missing half of the subprocess orchestration: the POC scripts
write files, the editor needs DB rows. Each function here is idempotent —
running it after a no-op subprocess won't duplicate takes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .paths import SongPaths
from ..store import connection


def refresh_song_from_files(
    *, conn, song_id: int, paths: SongPaths,
) -> None:
    """Copy character_brief.json and storyboard.json text into the songs row."""
    now = time.time()
    if paths.world_brief_json.exists():
        data = json.loads(paths.world_brief_json.read_text())
        brief = data.get("brief") if isinstance(data, dict) else str(data)
        conn.execute(
            "UPDATE songs SET world_brief = ?, updated_at = ? WHERE id = ?",
            (brief, now, song_id),
        )
    if paths.storyboard_json.exists():
        sb = json.loads(paths.storyboard_json.read_text())
        arc = sb.get("sequence_arc") if isinstance(sb, dict) else None
        if arc is not None:
            conn.execute(
                "UPDATE songs SET sequence_arc = ?, updated_at = ? WHERE id = ?",
                (arc, now, song_id),
            )
        # Replace per-scene beat / camera_intent / subject_focus / prev / next
        # for scenes where prompt_is_user_authored=0 so user edits survive.
        for shot in sb.get("shots", []):
            idx = shot.get("index")
            if idx is None:
                continue
            conn.execute("""
                UPDATE scenes SET
                    beat = CASE WHEN ? THEN ? ELSE beat END,
                    camera_intent = CASE WHEN ? THEN ? ELSE camera_intent END,
                    subject_focus = CASE WHEN ? THEN ? ELSE subject_focus END,
                    prev_link = ?,
                    next_link = ?,
                    updated_at = ?
                WHERE song_id = ? AND scene_index = ?
            """, (
                shot.get("beat") is not None, shot.get("beat"),
                shot.get("camera_intent") is not None, shot.get("camera_intent"),
                shot.get("subject_focus") is not None, shot.get("subject_focus"),
                shot.get("prev_link"),
                shot.get("next_link"),
                now, song_id, idx,
            ))


def import_image_prompts(
    *, conn, song_id: int, paths: SongPaths,
) -> int:
    """Write image_prompts.json entries into scenes.image_prompt. Respects
    prompt_is_user_authored — never overwrites a user-authored prompt."""
    if not paths.image_prompts_json.exists():
        return 0
    prompts = json.loads(paths.image_prompts_json.read_text())
    now = time.time()
    n = 0
    for key, value in prompts.items():
        # Keys look like "shot_042" (zero-padded) in POC 29 output.
        try:
            idx = int(key.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        updated = conn.execute("""
            UPDATE scenes SET image_prompt = ?, updated_at = ?
            WHERE song_id = ? AND scene_index = ? AND prompt_is_user_authored = 0
        """, (value, now, song_id, idx)).rowcount
        n += updated
    return n


def import_new_keyframe_takes(
    *, conn, song_id: int, paths: SongPaths,
    source_run_id: Optional[int], quality_mode: str,
    newer_than: Optional[float] = None,
    only_scene_index: Optional[int] = None,
) -> int:
    """Import new keyframes as takes. Two modes:

    - source_run_id is None: import case. A take is new only if no existing
      take row points at the same asset_path.
    - source_run_id is set: regen case. Archive the keyframe to a versioned
      path under keyframes/archive/ (preserving prior takes that still point
      at the original file), then insert a take at the archive path.

    `newer_than` (optional): only consider keyframe files whose mtime is
    >= this value. Used to restrict a stage run to files the subprocess
    just wrote.
    `only_scene_index` (optional): restrict to a single scene (regen case).
    """
    import shutil
    if not paths.keyframes_dir.exists():
        return 0
    archive_dir = paths.keyframes_dir / "archive"
    now = time.time()
    n = 0
    where = "WHERE song_id = ?"
    params: list = [song_id]
    if only_scene_index is not None:
        where += " AND scene_index = ?"
        params.append(only_scene_index)
    scenes = conn.execute(
        f"SELECT id, scene_index, selection_pinned FROM scenes {where}", params,
    ).fetchall()
    for s in scenes:
        idx = s["scene_index"]
        kf = paths.keyframes_dir / f"keyframe_{idx:03d}.png"
        if not kf.exists():
            continue
        if newer_than is not None and kf.stat().st_mtime < newer_than:
            continue
        if source_run_id is not None:
            # Regen case: archive to a versioned filename so prior takes'
            # asset_path keeps pointing at something real on disk.
            archive_dir.mkdir(exist_ok=True)
            archived = archive_dir / f"keyframe_{idx:03d}_run{source_run_id}.png"
            if not archived.exists():
                shutil.copyfile(kf, archived)
            asset_path = str(archived)
            dup = conn.execute(
                "SELECT id FROM takes WHERE scene_id = ? AND artefact_kind = 'keyframe' "
                "AND asset_path = ? AND source_run_id = ?",
                (s["id"], asset_path, source_run_id),
            ).fetchone()
            if dup is not None:
                continue
        else:
            asset_path = str(kf)
            # Idempotent-re-import dedup: skip only if we already have a take
            # at this path AND newer_than didn't flag this file as fresh. If
            # newer_than is set and passed the filter above, treat as new.
            if newer_than is None:
                dup = conn.execute(
                    "SELECT id FROM takes WHERE scene_id = ? AND artefact_kind = 'keyframe' "
                    "AND asset_path = ?",
                    (s["id"], asset_path),
                ).fetchone()
                if dup is not None:
                    continue
        cur = conn.execute(
            "INSERT INTO takes (scene_id, artefact_kind, asset_path, "
            "source_run_id, quality_mode, created_by, created_at) "
            "VALUES (?, 'keyframe', ?, ?, ?, 'editor', ?)",
            (s["id"], asset_path, source_run_id, quality_mode, now),
        )
        if not s["selection_pinned"]:
            conn.execute(
                "UPDATE scenes SET selected_keyframe_take_id = ?, updated_at = ? "
                "WHERE id = ?",
                (cur.lastrowid, now, s["id"]),
            )
        _clear_stale_flag(conn, s["id"], "keyframe_stale")
        n += 1
    return n


def import_new_clip_takes(
    *, conn, song_id: int, paths: SongPaths,
    source_run_id: Optional[int], quality_mode: str,
    only_scene_index: Optional[int] = None,
    newer_than: Optional[float] = None,
) -> int:
    """Same pattern as keyframes but for clips."""
    import shutil
    if not paths.clips_dir.exists():
        return 0
    archive_dir = paths.clips_dir / "archive"
    now = time.time()
    n = 0
    where = "WHERE song_id = ?"
    params: list = [song_id]
    if only_scene_index is not None:
        where += " AND scene_index = ?"
        params.append(only_scene_index)
    scenes = conn.execute(
        f"SELECT id, scene_index, selection_pinned FROM scenes {where}", params,
    ).fetchall()
    for s in scenes:
        idx = s["scene_index"]
        clip = paths.clips_dir / f"clip_{idx:03d}.mp4"
        if not clip.exists() or clip.stat().st_size < 100:
            continue
        if newer_than is not None and clip.stat().st_mtime < newer_than:
            continue
        if source_run_id is not None:
            archive_dir.mkdir(exist_ok=True)
            archived = archive_dir / f"clip_{idx:03d}_run{source_run_id}.mp4"
            if not archived.exists():
                shutil.copyfile(clip, archived)
            asset_path = str(archived)
            dup = conn.execute(
                "SELECT id FROM takes WHERE scene_id = ? AND artefact_kind = 'clip' "
                "AND asset_path = ? AND source_run_id = ?",
                (s["id"], asset_path, source_run_id),
            ).fetchone()
            if dup is not None:
                continue
        else:
            asset_path = str(clip)
            if newer_than is None:
                dup = conn.execute(
                    "SELECT id FROM takes WHERE scene_id = ? AND artefact_kind = 'clip' "
                    "AND asset_path = ?",
                    (s["id"], asset_path),
                ).fetchone()
                if dup is not None:
                    continue
        cur = conn.execute(
            "INSERT INTO takes (scene_id, artefact_kind, asset_path, "
            "source_run_id, quality_mode, created_by, created_at) "
            "VALUES (?, 'clip', ?, ?, ?, 'editor', ?)",
            (s["id"], asset_path, source_run_id, quality_mode, now),
        )
        if not s["selection_pinned"]:
            conn.execute(
                "UPDATE scenes SET selected_clip_take_id = ?, updated_at = ? "
                "WHERE id = ?",
                (cur.lastrowid, now, s["id"]),
            )
        _clear_stale_flag(conn, s["id"], "clip_stale")
        n += 1
    return n


def _clear_stale_flag(conn, scene_id: int, flag: str) -> None:
    row = conn.execute(
        "SELECT dirty_flags FROM scenes WHERE id = ?", (scene_id,),
    ).fetchone()
    if not row or not row["dirty_flags"]:
        return
    try:
        flags = json.loads(row["dirty_flags"])
    except (ValueError, TypeError):
        return
    if flag not in flags:
        return
    flags = [f for f in flags if f != flag]
    conn.execute(
        "UPDATE scenes SET dirty_flags = ? WHERE id = ?",
        (json.dumps(sorted(set(flags))), scene_id),
    )
