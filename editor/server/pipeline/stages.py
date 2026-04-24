"""Story 9 — real stage handlers.

Each stage corresponds to a phase of pocs/29-full-song/scripts/gen_keyframes.py:
- transcribe: runs make_shots.py (WhisperX cache → shots.json)
- world-brief: Pass A inside gen_keyframes.py
- storyboard:  Pass C inside gen_keyframes.py
- image-prompts: Pass B inside gen_keyframes.py
- keyframes:   Gemini image loop inside gen_keyframes.py

gen_keyframes.py is resumable: if character_brief.json exists it skips Pass A,
etc. So the editor's stage handlers work by (a) optionally deleting the
cached output for a re-run, (b) invoking the script, (c) reimporting outputs
into the DB. Running "world-brief" when nothing is cached will also populate
the downstream stages as a side effect — that's the design intent (Cheaper
overall than separate invocations, and gen_keyframes.py's resume logic means
subsequent runs are cheap).

A test fake-script can be substituted via the `script_path` argument so tests
verify the orchestration layer without Gemini calls.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional

from .paths import SongPaths, poc_scripts_root, resolve_song_paths
from .rescan import (
    import_image_prompts,
    import_new_keyframe_takes,
    refresh_song_from_files,
)
from .subprocess_runner import ProgressEvent, RunResult, run_script
from ..store import connection
from .. import config as _cfg


StageKey = Literal[
    "transcribe", "world-brief", "storyboard", "image-prompts", "keyframes",
]


@dataclass
class StageResult:
    ok: bool
    returncode: int
    new_keyframes: int
    new_prompts: int
    stdout_tail: str
    stderr_tail: str
    duration_s: float


# Which cache files each stage-redo must delete for the PRD's "re-run marks
# downstream stale" contract.
_REDO_CACHE_TO_DELETE: dict[StageKey, list[str]] = {
    "transcribe":    ["shots.json", "character_brief.json", "storyboard.json",
                      "image_prompts.json", "keyframes"],
    "world-brief":   ["character_brief.json", "storyboard.json",
                      "image_prompts.json", "keyframes"],
    "storyboard":    ["storyboard.json", "image_prompts.json", "keyframes"],
    "image-prompts": ["image_prompts.json", "keyframes"],
    "keyframes":     ["keyframes"],
}


def _invalidate_cache(run_dir: Path, stage: StageKey) -> None:
    for name in _REDO_CACHE_TO_DELETE[stage]:
        target = run_dir / name
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink(missing_ok=True)


def _tail(s: str, n: int = 4000) -> str:
    return s[-n:] if len(s) > n else s


def run_gen_keyframes_for_stage(
    *,
    song_slug: str,
    song_filter: str,
    song_abstraction: int,
    song_quality_mode: str,
    source_run_id: Optional[int],
    stage: StageKey,
    redo: bool = False,
    script_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[ProgressEvent], None]] = None,
    db_path: Optional[Path] = None,
    outputs_root: Optional[Path] = None,
    music_root: Optional[Path] = None,
) -> StageResult:
    """Execute one editor stage via gen_keyframes.py (or a fake substitute).

    Resolves song paths, optionally invalidates cache for a re-run, invokes
    the script, then rescans the run_dir to pull new takes into the DB.
    """
    outputs_root = outputs_root or _cfg.OUTPUTS_DIR
    music_root = music_root or _cfg.MUSIC_DIR
    db_path = db_path or _cfg.DB_PATH
    script = script_path or (poc_scripts_root() / "gen_keyframes.py")

    paths = resolve_song_paths(
        outputs_root=Path(outputs_root),
        music_root=Path(music_root),
        slug=song_slug,
    )
    paths.run_dir.mkdir(parents=True, exist_ok=True)

    if redo:
        _invalidate_cache(paths.run_dir, stage)

    # Snapshot the clock BEFORE the subprocess so rescan can attribute only
    # the files written during this run.
    run_start = time.time()

    # Guard: the `transcribe` stage has its own handler path (WhisperX) and
    # never calls gen_keyframes.py. The other four stages share one invocation.
    if stage == "transcribe":
        return _run_transcribe(
            song_slug=song_slug, paths=paths, source_run_id=source_run_id,
            progress_cb=progress_cb, db_path=Path(db_path),
            song_quality_mode=song_quality_mode,
        )

    # shots.json must exist before gen_keyframes can run.
    if not paths.shots_json.exists():
        return StageResult(
            ok=False, returncode=126, new_keyframes=0, new_prompts=0,
            stdout_tail="", stderr_tail=f"shots.json missing at {paths.shots_json}",
            duration_s=0.0,
        )

    # Invoke gen_keyframes.py. Its stdout stream is parsed for progress.
    args = [
        "--song", song_slug,
        "--lyrics", str(paths.lyrics_txt),
        "--shots", str(paths.shots_json),
        "--run-dir", str(paths.run_dir),
        "--filter", song_filter,
        "--abstraction", str(song_abstraction),
    ]
    result = run_script(
        script, args,
        progress_cb=progress_cb,
        timeout_s=None,
    )

    # Re-scan run_dir into the DB regardless of exit code — we want partial
    # progress captured.
    with connection(Path(db_path)) as conn:
        song = conn.execute(
            "SELECT id FROM songs WHERE slug = ?", (song_slug,),
        ).fetchone()
        song_id = song["id"] if song else None
        new_prompts = 0
        new_keyframes = 0
        if song_id is not None:
            refresh_song_from_files(conn=conn, song_id=song_id, paths=paths)
            new_prompts = import_image_prompts(
                conn=conn, song_id=song_id, paths=paths,
            )
            # Only import keyframes whose files were written after the run
            # started — existing files from before the subprocess started
            # are already represented by earlier takes.
            new_keyframes = import_new_keyframe_takes(
                conn=conn, song_id=song_id, paths=paths,
                source_run_id=source_run_id, quality_mode=song_quality_mode,
                newer_than=run_start,
            )

    return StageResult(
        ok=result.ok,
        returncode=result.returncode,
        new_keyframes=new_keyframes,
        new_prompts=new_prompts,
        stdout_tail=_tail(result.stdout),
        stderr_tail=_tail(result.stderr),
        duration_s=result.duration_s,
    )


def _run_transcribe(
    *, song_slug: str, paths: SongPaths,
    source_run_id: Optional[int],
    progress_cb: Optional[Callable[[ProgressEvent], None]],
    db_path: Path,
    song_quality_mode: str,
) -> StageResult:
    """Produce shots.json. Uses pocs/29-full-song/scripts/make_shots.py.

    If shots.json already exists and the lyrics/wav haven't changed, make_shots
    is a no-op — safe to re-run. If WhisperX cache exists in
    pocs/29-full-song/whisperx_cache/ make_shots uses it; otherwise it runs
    the full alignment (slow, ~30s per minute of audio).
    """
    script = poc_scripts_root() / "make_shots.py"
    if not script.exists():
        return StageResult(
            ok=False, returncode=126, new_keyframes=0, new_prompts=0,
            stdout_tail="",
            stderr_tail=f"make_shots.py not found at {script}",
            duration_s=0.0,
        )
    args = [
        "--song", song_slug,
        "--audio", str(paths.music_wav),
        "--lyrics", str(paths.lyrics_txt),
        "--out-dir", str(paths.run_dir),
    ]
    result = run_script(script, args, progress_cb=progress_cb)
    # No new takes on transcribe — only shots.json is produced.
    return StageResult(
        ok=result.ok,
        returncode=result.returncode,
        new_keyframes=0,
        new_prompts=0,
        stdout_tail=_tail(result.stdout),
        stderr_tail=_tail(result.stderr),
        duration_s=result.duration_s,
    )
