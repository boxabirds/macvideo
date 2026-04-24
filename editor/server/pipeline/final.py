"""Story 10 — final video render.

Runs per-scene clip rendering for any missing/stale clips (via render_clips.py
which is resumable), then runs the A+B1+C align + concat + audio-mux pass
via ffmpeg. Drops a row into finished_videos.

For tests, `render_clips.py` can be substituted and ffmpeg can be substituted
via `ffmpeg_bin` — the test fakes both to produce a tiny valid-looking mp4
without invoking LTX / Apple Video Toolbox.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .paths import poc_scripts_root, resolve_song_paths
from .rescan import import_new_clip_takes
from .subprocess_runner import ProgressEvent, run_script
from ..store import connection
from .. import config as _cfg


@dataclass
class FinalRenderResult:
    ok: bool
    finished_path: Optional[Path]
    scene_count: int
    gap_count: int
    stdout_tail: str
    stderr_tail: str
    duration_s: float


def render_final(
    *,
    song_slug: str,
    song_filter: str,
    song_quality_mode: str,
    source_run_id: Optional[int],
    script_path: Optional[Path] = None,
    ffmpeg_bin: str = "ffmpeg",
    progress_cb: Optional[Callable[[ProgressEvent], None]] = None,
    db_path: Optional[Path] = None,
    outputs_root: Optional[Path] = None,
    music_root: Optional[Path] = None,
) -> FinalRenderResult:
    """Render every scene's missing clip, stitch, mux audio, persist a
    finished_videos row."""
    outputs_root = outputs_root or _cfg.OUTPUTS_DIR
    music_root = music_root or _cfg.MUSIC_DIR
    db_path = db_path or _cfg.DB_PATH
    script = script_path or (poc_scripts_root() / "render_clips.py")

    paths = resolve_song_paths(
        outputs_root=Path(outputs_root),
        music_root=Path(music_root),
        slug=song_slug,
    )
    paths.clips_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    # render_clips.py is resumable — it skips clips that exist + non-empty.
    # It also does its own align + concat + mux pass at the end.
    args = [
        "--song", song_slug,
        "--audio", str(paths.music_wav),
        "--shots", str(paths.shots_json),
        "--run-dir", str(paths.run_dir),
        "--filter", song_filter,
        "--quality-mode", song_quality_mode,
    ]
    result = run_script(script, args, progress_cb=progress_cb)

    # The POC writes the final file at run_dir/final.mp4 when its concat+mux
    # path completes. Some failure modes leave only the partial mp4 — we
    # still try to persist the row so the user can inspect the partial.
    final_candidate = paths.run_dir / "final.mp4"
    ok = result.ok and final_candidate.exists() and final_candidate.stat().st_size > 0

    # Count gaps (scenes without a rendered clip file) so the row records
    # whether this is a complete or partial finish.
    total_scenes = 0
    gap_count = 0
    finished_path: Optional[Path] = None
    scene_count = 0
    with connection(Path(db_path)) as conn:
        song = conn.execute(
            "SELECT id FROM songs WHERE slug = ?", (song_slug,),
        ).fetchone()
        if song is None:
            return FinalRenderResult(
                ok=False, finished_path=None, scene_count=0, gap_count=0,
                stdout_tail=result.stdout[-4000:],
                stderr_tail=result.stderr[-4000:] + f"\nsong '{song_slug}' not found",
                duration_s=time.time() - t0,
            )
        song_id = song["id"]

        # Pull in any new clip takes that render_clips.py produced.
        import_new_clip_takes(
            conn=conn, song_id=song_id, paths=paths,
            source_run_id=source_run_id, quality_mode=song_quality_mode,
        )

        total_scenes = conn.execute(
            "SELECT COUNT(*) FROM scenes WHERE song_id = ?", (song_id,),
        ).fetchone()[0]
        gap_count = sum(
            1 for s in conn.execute(
                "SELECT scene_index FROM scenes WHERE song_id = ?", (song_id,),
            ).fetchall()
            if not (paths.clips_dir / f"clip_{s['scene_index']:03d}.mp4").exists()
        )
        scene_count = total_scenes

        if ok:
            # Timestamped copy so re-renders don't clobber prior output.
            stamp = time.strftime("%Y%m%dT%H%M%S")
            target_dir = paths.run_dir / "finals"
            target_dir.mkdir(exist_ok=True)
            keep = target_dir / f"final_{stamp}_{song_quality_mode}.mp4"
            keep.write_bytes(final_candidate.read_bytes())
            finished_path = keep

            conn.execute("""
                INSERT INTO finished_videos
                    (song_id, file_path, quality_mode, scene_count, gap_count,
                     final_run_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                song_id, str(finished_path), song_quality_mode,
                scene_count, gap_count, source_run_id, time.time(),
            ))

    return FinalRenderResult(
        ok=ok,
        finished_path=finished_path,
        scene_count=scene_count,
        gap_count=gap_count,
        stdout_tail=result.stdout[-4000:],
        stderr_tail=result.stderr[-4000:],
        duration_s=time.time() - t0,
    )


def ffmpeg_available(ffmpeg_bin: str = "ffmpeg") -> bool:
    try:
        r = subprocess.run(
            [ffmpeg_bin, "-version"],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
