"""Story 14: HTTP endpoint for audio-only transcription.

POST /api/songs/{slug}/audio-transcribe
  query: force=true|false (default false)

Spawns a background task that runs the Demucs+WhisperX pipeline
(editor.server.pipeline.audio_transcribe.run_audio_transcribe), then on
ok=True hands off to the existing forced-alignment stage from Story 12
(_run_transcribe in editor.server.pipeline.stages) so scenes land in the
DB. The whole sequence is tracked under a single regen_runs row with
scope='stage_audio_transcribe'.

Single-flight discipline: blocks if any pending/running stage_transcribe
or stage_audio_transcribe run already exists for this slug — the user
can't have two transcription paths racing.
"""

from __future__ import annotations

import asyncio
import threading
import wave
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import config as _cfg
from ..pipeline.audio_transcribe import (
    PHASE_ALIGNING, PHASE_SEPARATING_VOCALS, PHASE_TRANSCRIBING,
    run_audio_transcribe,
)
from ..pipeline.paths import resolve_song_paths
from ..pipeline.stages import _run_transcribe
from ..regen.queue import RegenJob, keyframe_queue
from ..regen.runs import (
    create_run, get_run, update_run_phase,
)
from ..store import connection
from .common import get_db


router = APIRouter()


_MIN_AUDIO_DURATION_S = 1.0


def _audio_duration_or_none(wav_path: Path) -> float | None:
    if not wav_path.exists():
        return None
    try:
        with wave.open(str(wav_path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        # Treat unreadable as missing — matches the design's audio_missing
        # contract better than surfacing a generic 500.
        return None


def _conflict_run_id(conn, song_id: int) -> int | None:
    """Cross-stage single-flight: any pending/running transcribe-family run."""
    row = conn.execute(
        "SELECT id FROM regen_runs WHERE song_id = ? "
        "AND scope IN ('stage_audio_transcribe', 'stage_transcribe') "
        "AND status IN ('pending', 'running') LIMIT 1",
        (song_id,),
    ).fetchone()
    return row["id"] if row else None


@router.post("/songs/{slug}/audio-transcribe")
async def trigger_audio_transcribe(
    slug: str,
    force: bool = Query(default=False),
    conn=Depends(get_db),
):
    song = conn.execute(
        "SELECT id, quality_mode, filter, abstraction FROM songs WHERE slug = ?",
        (slug,),
    ).fetchone()
    if not song:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")

    paths = resolve_song_paths(
        outputs_root=_cfg.OUTPUTS_DIR,
        music_root=_cfg.MUSIC_DIR,
        slug=slug,
    )

    # Preflight: audio file must be present and at least 1.0s long.
    duration = _audio_duration_or_none(paths.music_wav)
    if duration is None:
        raise HTTPException(status_code=422, detail={
            "code": "audio_missing",
            "detail": f"audio file not found at {paths.music_wav.name}",
        })
    if duration < _MIN_AUDIO_DURATION_S:
        raise HTTPException(status_code=422, detail={
            "code": "audio_too_short",
            "detail": f"audio is only {duration:.2f}s; need ≥ {_MIN_AUDIO_DURATION_S}s",
        })

    # Single-flight: refuse if either transcribe scope is already running.
    conflict_id = _conflict_run_id(conn, song["id"])
    if conflict_id is not None:
        raise HTTPException(status_code=409, detail={
            "code": "single_flight_conflict",
            "detail": f"a transcribe run is already in progress (run {conflict_id})",
        })

    # Overwrite guard: existing lyrics file must be confirmed via force=true.
    if paths.lyrics_txt.exists() and not force:
        raise HTTPException(status_code=409, detail={
            "code": "overwrite_required",
            "detail": "lyrics file already exists; retry with force=true",
        })

    run_id = create_run(
        conn, scope="stage_audio_transcribe", song_id=song["id"],
    )
    run = get_run(conn, run_id)
    assert run is not None

    slug_captured = slug
    db_path = _cfg.DB_PATH
    music_root = _cfg.MUSIC_DIR
    outputs_root = _cfg.OUTPUTS_DIR
    quality_mode = song["quality_mode"] or "draft"

    async def handler(r):  # noqa: ANN001
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: _orchestrate(
                slug=slug_captured, run_id=r.id, force=force,
                db_path=db_path, music_root=music_root, outputs_root=outputs_root,
                quality_mode=quality_mode,
            ),
        )

    keyframe_queue.submit(RegenJob(run=run, handler=handler))
    return {"run_id": run_id, "status": "pending"}


def _orchestrate(
    *, slug: str, run_id: int, force: bool,
    db_path: Path, music_root: Path, outputs_root: Path,
    quality_mode: str,
) -> dict:
    """Run audio_transcribe → on success, run_transcribe (Story 12 alignment)."""
    paths = resolve_song_paths(
        outputs_root=outputs_root, music_root=music_root, slug=slug,
    )

    def _set_phase(phase: str) -> None:
        with connection(db_path) as c:
            update_run_phase(c, run_id, phase)

    def _progress_cb(phase: str, _pct: float) -> None:
        # Phase transitions are the only signal we surface to the run row;
        # within-phase pct is a future enhancement.
        _set_phase(phase)

    cancel = threading.Event()
    audio_result = run_audio_transcribe(
        slug=slug, paths=paths, run_id=run_id, force=force,
        progress_cb=_progress_cb, cancel_event=cancel,
    )

    if not audio_result.ok:
        # The queue layer maps a non-ok dict to status='failed'.
        return {
            "ok": False,
            "stdout_tail": audio_result.stdout_tail,
            "stderr_tail": audio_result.stderr_tail,
            "returncode": audio_result.returncode,
        }
    if audio_result.cancelled:
        return {"ok": False, "stderr_tail": "cancelled"}

    # Phase 3: hand off to forced alignment + scene derivation.
    _set_phase(PHASE_ALIGNING)
    align_result = _run_transcribe(
        song_slug=slug, paths=paths, source_run_id=run_id,
        progress_cb=None, db_path=db_path,
        song_quality_mode=quality_mode,
        music_root=music_root, outputs_root=outputs_root,
    )
    return {
        "ok": align_result.ok,
        "returncode": align_result.returncode,
        "stdout_tail": align_result.stdout_tail,
        "stderr_tail": align_result.stderr_tail,
    }
