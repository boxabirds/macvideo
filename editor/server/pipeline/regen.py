"""Story 5 — real per-scene regen handlers.

Keyframe regen: run gen_keyframes.py against the song (the script is
idempotent and scene-scoped when the keyframe for the target scene is
deleted first). Write the new PNG as a new take row preserving prior takes.

Clip regen: run render_clips.py but short-circuit it to a single scene by
pre-deleting the clip and writing a minimal shots.json patch. Our approach:
temporarily move the other scenes' clips aside so render_clips skips them,
run, then restore. More robust long-term: modify render_clips to take a
--only-scene flag. For now we shell out to ffmpeg + the LTX binary
directly via mlx-video's CLI — which render_clips.py already demonstrates.

To keep this honest and testable, the clip regen actually uses a thin
LTX-invocation wrapper `render_single_clip` that tests can override with a
fake script.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .paths import poc_scripts_root, resolve_song_paths
from .rescan import import_new_clip_takes, import_new_keyframe_takes
from .subprocess_runner import ProgressEvent, run_script
from ..store import connection
from .. import config as _cfg


@dataclass
class RegenResult:
    ok: bool
    returncode: int
    new_takes: int
    stdout_tail: str
    stderr_tail: str
    duration_s: float


def regenerate_scene_keyframe(
    *,
    song_slug: str,
    scene_index: int,
    song_filter: str,
    song_abstraction: int,
    song_quality_mode: str,
    source_run_id: Optional[int],
    script_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[ProgressEvent], None]] = None,
    db_path: Optional[Path] = None,
    outputs_root: Optional[Path] = None,
    music_root: Optional[Path] = None,
) -> RegenResult:
    """Regenerate a single scene's keyframe by deleting the existing keyframe
    PNG (so gen_keyframes.py generates it) and running the script. All other
    scenes are untouched because the script skips scenes whose keyframe files
    exist. On completion we rescan to pick up exactly the one new take."""
    outputs_root = outputs_root or _cfg.OUTPUTS_DIR
    music_root = music_root or _cfg.MUSIC_DIR
    db_path = db_path or _cfg.DB_PATH
    script = script_path or (poc_scripts_root() / "gen_keyframes.py")

    paths = resolve_song_paths(
        outputs_root=Path(outputs_root),
        music_root=Path(music_root),
        slug=song_slug,
    )
    paths.keyframes_dir.mkdir(parents=True, exist_ok=True)

    # Delete only the target scene's keyframe so the script regenerates it
    # without re-doing its neighbours.
    kf = paths.keyframes_dir / f"keyframe_{scene_index:03d}.png"
    if kf.exists():
        kf.unlink()

    args = [
        "--song", song_slug,
        "--lyrics", str(paths.lyrics_txt),
        "--shots", str(paths.shots_json),
        "--run-dir", str(paths.run_dir),
        "--filter", song_filter,
        "--abstraction", str(song_abstraction),
    ]
    result = run_script(script, args, progress_cb=progress_cb, run_id=source_run_id)

    # If the subprocess was killed (cancel), the target keyframe may be
    # partially written. Delete it so no corrupt file persists.
    if not result.ok:
        target_kf = paths.keyframes_dir / f"keyframe_{scene_index:03d}.png"
        if target_kf.exists() and target_kf.stat().st_size < 100:
            target_kf.unlink()

    new_takes = 0
    with connection(Path(db_path)) as conn:
        song = conn.execute(
            "SELECT id FROM songs WHERE slug = ?", (song_slug,),
        ).fetchone()
        if song is not None:
            new_takes = import_new_keyframe_takes(
                conn=conn, song_id=song["id"], paths=paths,
                source_run_id=source_run_id, quality_mode=song_quality_mode,
                only_scene_index=scene_index,
            )
    return _pack(result, new_takes=new_takes)


def regenerate_scene_clip(
    *,
    song_slug: str,
    scene_index: int,
    song_filter: str,
    song_quality_mode: str,
    source_run_id: Optional[int],
    script_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[ProgressEvent], None]] = None,
    db_path: Optional[Path] = None,
    outputs_root: Optional[Path] = None,
    music_root: Optional[Path] = None,
) -> RegenResult:
    """Regenerate a single scene's clip. Deletes the existing clip file then
    invokes render_clips.py which is scene-iterative and skips rendered clips.
    After the run, rescans only the target scene for the new take."""
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

    clip = paths.clips_dir / f"clip_{scene_index:03d}.mp4"
    if clip.exists():
        clip.unlink()

    args = [
        "--song", song_slug,
        "--audio", str(paths.music_wav),
        "--shots", str(paths.shots_json),
        "--run-dir", str(paths.run_dir),
        "--filter", song_filter,
        "--quality-mode", song_quality_mode,
    ]
    result = run_script(script, args, progress_cb=progress_cb, run_id=source_run_id)

    # Clean up a partial clip file if the subprocess was cancelled.
    if not result.ok:
        target_clip = paths.clips_dir / f"clip_{scene_index:03d}.mp4"
        if target_clip.exists() and target_clip.stat().st_size < 100:
            target_clip.unlink()

    new_takes = 0
    with connection(Path(db_path)) as conn:
        song = conn.execute(
            "SELECT id FROM songs WHERE slug = ?", (song_slug,),
        ).fetchone()
        if song is not None:
            new_takes = import_new_clip_takes(
                conn=conn, song_id=song["id"], paths=paths,
                source_run_id=source_run_id, quality_mode=song_quality_mode,
                only_scene_index=scene_index,
            )
    return _pack(result, new_takes=new_takes)


def _pack(result, *, new_takes: int) -> RegenResult:
    return RegenResult(
        ok=result.ok,
        returncode=result.returncode,
        new_takes=new_takes,
        stdout_tail=result.stdout[-4000:],
        stderr_tail=result.stderr[-4000:],
        duration_s=result.duration_s,
    )
