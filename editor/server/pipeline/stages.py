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
            music_root=Path(music_root), outputs_root=Path(outputs_root),
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
    music_root: Path,
    outputs_root: Path,
) -> StageResult:
    """Produce shots.json. Two subprocesses:
       1. whisperx_align.py — runs WhisperX forced alignment IF the cached
          aligned.json doesn't already exist for this slug.
       2. make_shots.py — derives shots from the alignment + lyric file.
    Then re-imports the song so the newly-produced scenes land in the DB.

    Test harnesses can swap either script via env vars:
      EDITOR_FAKE_WHISPERX_ALIGN, EDITOR_FAKE_MAKE_SHOTS.
    """
    poc_root = poc_scripts_root()
    align_script = Path(
        os.environ.get("EDITOR_FAKE_WHISPERX_ALIGN", str(poc_root / "whisperx_align.py")),
    )
    shots_script = Path(
        os.environ.get("EDITOR_FAKE_MAKE_SHOTS", str(poc_root / "make_shots.py")),
    )
    if not align_script.exists():
        return StageResult(
            ok=False, returncode=126, new_keyframes=0, new_prompts=0,
            stdout_tail="",
            stderr_tail=f"whisperx_align.py not found at {align_script}",
            duration_s=0.0,
        )
    if not shots_script.exists():
        return StageResult(
            ok=False, returncode=126, new_keyframes=0, new_prompts=0,
            stdout_tail="",
            stderr_tail=f"make_shots.py not found at {shots_script}",
            duration_s=0.0,
        )

    # Cache lives next to the scripts dir: pocs/29-full-song/whisperx_cache/.
    whisperx_cache = poc_root.parent / "whisperx_cache" / f"{song_slug}.aligned.json"

    align_stdout = ""
    align_stderr = ""
    align_duration = 0.0
    if not whisperx_cache.exists():
        align_args = [
            "--audio", str(paths.music_wav),
            "--out", str(whisperx_cache),
            "--lyrics", str(paths.lyrics_txt),
        ]
        align_result = run_script(align_script, align_args, progress_cb=progress_cb)
        align_stdout = align_result.stdout
        align_stderr = align_result.stderr
        align_duration = align_result.duration_s
        if not align_result.ok:
            return StageResult(
                ok=False, returncode=align_result.returncode,
                new_keyframes=0, new_prompts=0,
                stdout_tail=_tail(align_stdout),
                stderr_tail=_tail(align_stderr) or f"whisperx_align failed (code {align_result.returncode})",
                duration_s=align_duration,
            )

    # shots.json output dir must exist (run_dir is mkdir'd by the caller, but
    # be defensive here for direct-test invocations).
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    shots_args = [
        "--song", song_slug,
        "--whisperx", str(whisperx_cache),
        "--lyrics", str(paths.lyrics_txt),
        "--out", str(paths.shots_json),
    ]
    shots_result = run_script(shots_script, shots_args, progress_cb=progress_cb)
    if not shots_result.ok:
        return StageResult(
            ok=False, returncode=shots_result.returncode,
            new_keyframes=0, new_prompts=0,
            stdout_tail=_tail(align_stdout + shots_result.stdout),
            stderr_tail=_tail(shots_result.stderr) or "make_shots failed",
            duration_s=align_duration + shots_result.duration_s,
        )

    # Re-import the song so the newly-produced shots land in the DB as scene
    # rows. _import_one_song is the same path lifespan startup uses, so this
    # stays consistent with the rest of the importer's behaviour.
    from ..importer import _import_one_song
    _import_one_song(db_path, music_root, outputs_root, paths.music_wav)

    return StageResult(
        ok=True,
        returncode=shots_result.returncode,
        new_keyframes=0,
        new_prompts=0,
        stdout_tail=_tail(align_stdout + shots_result.stdout),
        stderr_tail=_tail(align_stderr + shots_result.stderr),
        duration_s=align_duration + shots_result.duration_s,
    )
