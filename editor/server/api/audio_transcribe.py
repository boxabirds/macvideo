"""Story 18: HTTP endpoint for audio-only transcription.

POST /api/songs/{slug}/audio-transcribe

Spawns a background task that runs the Demucs+WhisperX pipeline to produce
timestamped segments, then inserts scene rows directly into the DB. The
forced-alignment stage (Story 12) is no longer used. Tracked under a single
regen_runs row with scope='stage_audio_transcribe'.

Single-flight discipline: blocks if any workflow run is pending/running for
this slug.
"""

from __future__ import annotations

import asyncio
import threading
import time
import wave
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import config as _cfg
from ..pipeline.audio_transcribe import (
    PHASE_SEPARATING_VOCALS, PHASE_TRANSCRIBING,
    run_audio_transcribe,
)
from ..pipeline.paths import resolve_song_paths
from ..pipeline.preflight import preflight_stage
from ..pipeline.stages import StageResult
from ..regen.queue import RegenJob, keyframe_queue
from ..regen.runs import (
    create_run, get_run, update_run_phase, update_run_progress,
)
from ..store import connection
from ..workflow import (
    WorkflowActionRequest,
    WorkflowTransitionRejection,
    evaluate_song_workflow,
    plan_workflow_transition,
    transition_rejection_status,
)
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

    transcription_state = evaluate_song_workflow(conn, song["id"]).stages["transcription"].state
    action = "regenerate" if force and transcription_state in ("done", "stale") else "start"
    plan = plan_workflow_transition(
        conn,
        song_id=song["id"],
        request=WorkflowActionRequest(
            stage="transcription",
            action=action,
            run_scope="stage_audio_transcribe",
        ),
    )
    if isinstance(plan, WorkflowTransitionRejection):
        raise HTTPException(
            status_code=transition_rejection_status(plan),
            detail=plan.to_http_detail(),
        )
    if plan.outcome == "accept_noop":
        return {"run_id": None, "status": "done"}

    preflight = preflight_stage(slug=slug, stage="audio-transcribe")
    if not preflight.ok:
        raise HTTPException(status_code=422, detail=preflight.to_http_detail())

    run_id = create_run(
        conn, scope=plan.scope, song_id=song["id"],
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
) -> StageResult:
    """Run audio_transcribe and insert segments as scene rows.

    Story 18: WhisperX emits timestamped JSON segments. Insert one scene row
    per segment directly into the DB. No forced-alignment pass needed.
    """
    paths = resolve_song_paths(
        outputs_root=outputs_root, music_root=music_root, slug=slug,
    )

    def _set_progress(phase: str, pct: float) -> None:
        with connection(db_path) as c:
            update_run_phase(c, run_id, phase)
            update_run_progress(c, run_id, int(pct))

    def _progress_cb(phase: str, pct: float) -> None:
        _set_progress(phase, pct)

    cancel = threading.Event()
    audio_result = run_audio_transcribe(
        slug=slug, paths=paths, run_id=run_id, force=force,
        progress_cb=_progress_cb, cancel_event=cancel,
    )

    if not audio_result.ok:
        return StageResult(
            ok=False,
            returncode=audio_result.returncode,
            new_keyframes=0,
            new_prompts=0,
            stdout_tail=audio_result.stdout_tail,
            stderr_tail=audio_result.stderr_tail or audio_result.failing_phase or "failed",
            duration_s=audio_result.duration_s,
        )
    if audio_result.cancelled:
        return StageResult(
            ok=False,
            returncode=1,
            new_keyframes=0,
            new_prompts=0,
            stdout_tail="",
            stderr_tail="cancelled",
            duration_s=audio_result.duration_s,
        )

    # Insert scene rows from segments.
    with connection(db_path) as c:
        song = c.execute(
            "SELECT id FROM songs WHERE slug = ?", (slug,)
        ).fetchone()
        if not song:
            return StageResult(
                ok=False,
                returncode=1,
                new_keyframes=0,
                new_prompts=0,
                stdout_tail="",
                stderr_tail=f"song {slug} not found",
                duration_s=audio_result.duration_s,
            )

        now = time.time()
        for scene_index, segment in enumerate(audio_result.segments):
            target_text = segment.get("text", "")
            start_s = segment.get("start", 0.0)
            end_s = segment.get("end", 0.0)
            duration_s = end_s - start_s if end_s > start_s else 0.0

            c.execute(
                """
                INSERT INTO scenes (
                    song_id, scene_index, kind, target_text,
                    start_s, end_s, target_duration_s, num_frames,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    song["id"],
                    scene_index,
                    "lyric",
                    target_text,
                    start_s,
                    end_s,
                    duration_s,
                    0,
                    now,
                    now,
                ),
            )
        c.commit()

    return StageResult(
        ok=True,
        returncode=0,
        new_keyframes=0,
        new_prompts=0,
        stdout_tail=audio_result.stdout_tail,
        stderr_tail="",
        duration_s=audio_result.duration_s,
    )
