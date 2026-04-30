"""Regen orchestration HTTP routes.

Routes:
    POST   /api/songs/:slug/scenes/:idx/takes
                trigger scene-level keyframe or clip regen (story 5)
    POST   /api/regen/:run_id/cancel
                cancel a running regen (story 5)
    GET    /events/regen
                SSE stream of regen lifecycle events (story 5, 9, 10)
    GET    /api/songs/:slug/regen
                list recent runs for a song
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import config as _cfg
from ..pipeline.regen import regenerate_scene_clip, regenerate_scene_keyframe
from ..regen.events import hub
from ..regen.queue import clip_queue, keyframe_queue, RegenJob
from ..regen.runs import (
    RegenRun,
    create_run,
    get_run,
    list_song_runs,
    update_run_status,
)
from .common import get_db


def _override_gen_keyframes() -> Optional[Path]:
    p = os.environ.get("EDITOR_FAKE_GEN_KEYFRAMES")
    return Path(p) if p else None


def _override_render_clips() -> Optional[Path]:
    p = os.environ.get("EDITOR_FAKE_RENDER_CLIPS")
    return Path(p) if p else None


router = APIRouter()
events_router = APIRouter()


_OBSOLETE_AUDIO_TRANSCRIBE_USAGE = (
    "pocs/30-whisper-timestamped/scripts/transcribe_whisperx_noprompt.py"
)


def _normalize_run_for_response(run: dict) -> dict:
    error = run.get("error")
    if isinstance(error, str) and _OBSOLETE_AUDIO_TRANSCRIBE_USAGE in error:
        run = {**run}
        run["status"] = "cancelled"
        run["error"] = None
    return run


class TakeTriggerBody(BaseModel):
    artefact_kind: Literal["keyframe", "clip"]
    trigger: Literal["regen", "cli-observed"] = "regen"


class TakeTriggerResponse(BaseModel):
    run_id: int
    status: str
    estimated_seconds: int


@router.post("/songs/{slug}/scenes/{idx}/takes", response_model=TakeTriggerResponse)
async def trigger_take(slug: str, idx: int, body: TakeTriggerBody, conn=Depends(get_db)):
    row = conn.execute("""
        SELECT s.id AS scene_id, s.image_prompt, s.scene_index,
               g.id AS song_id, g.slug, g.filter, g.abstraction, g.quality_mode
        FROM scenes s JOIN songs g ON g.id = s.song_id
        WHERE g.slug = ? AND s.scene_index = ?
    """, (slug, idx)).fetchone()
    if row is None:
        raise HTTPException(status_code=404,
                            detail=f"scene {idx} of song '{slug}' not found")

    conflict = conn.execute("""
        SELECT id FROM regen_runs
        WHERE song_id = ? AND scene_id = ? AND artefact_kind = ?
          AND status IN ('pending', 'running')
        LIMIT 1
    """, (row["song_id"], row["scene_id"], body.artefact_kind)).fetchone()
    if conflict:
        raise HTTPException(status_code=409,
                            detail=f"regen for scene {idx} {body.artefact_kind} already in progress (run {conflict['id']})")

    if body.artefact_kind == "keyframe" and not row["image_prompt"]:
        raise HTTPException(status_code=422,
                            detail=f"scene {idx} has no image_prompt to regenerate")

    scope = "scene_keyframe" if body.artefact_kind == "keyframe" else "scene_clip"
    quality_mode = row["quality_mode"] if body.artefact_kind == "clip" else None

    run_id = create_run(
        conn, scope=scope, song_id=row["song_id"], scene_id=row["scene_id"],
        artefact_kind=body.artefact_kind, quality_mode=quality_mode,
    )
    run = get_run(conn, run_id)
    if run is None:
        raise HTTPException(status_code=500, detail="run creation failed")

    slug_captured = row["slug"]
    scene_index = row["scene_index"]
    song_filter = row["filter"] or "charcoal"
    song_abstraction = row["abstraction"] or 25
    song_quality_mode = row["quality_mode"] or "draft"

    if body.artefact_kind == "keyframe":
        async def handler(r):  # noqa: ANN001
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: regenerate_scene_keyframe(
                    song_slug=slug_captured, scene_index=scene_index,
                    song_filter=song_filter, song_abstraction=song_abstraction,
                    song_quality_mode=song_quality_mode,
                    source_run_id=r.id,
                    script_path=_override_gen_keyframes(),
                ),
            )
        queue = keyframe_queue
        estimate = 15
    else:
        async def handler(r):  # noqa: ANN001
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: regenerate_scene_clip(
                    song_slug=slug_captured, scene_index=scene_index,
                    song_filter=song_filter,
                    song_quality_mode=song_quality_mode,
                    source_run_id=r.id,
                    script_path=_override_render_clips(),
                ),
            )
        queue = clip_queue
        estimate = 1200 if quality_mode == "final" else 120

    queue.submit(RegenJob(run=run, handler=handler))
    return TakeTriggerResponse(run_id=run_id, status="pending", estimated_seconds=estimate)


@router.post("/regen/{run_id}/cancel")
async def cancel_run(run_id: int, conn=Depends(get_db)):
    from ..pipeline.subprocess_runner import cancel_run as cancel_subprocess
    run = get_run(conn, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=409,
                            detail=f"run {run_id} already in terminal state '{run.status}'")
    # SIGTERM the subprocess (SIGKILL after 2s). Its rescan cleanup in
    # regen.py then deletes any partial file so no corrupt asset lingers.
    signalled = cancel_subprocess(run_id)
    update_run_status(conn, run_id, "cancelled")
    return {
        "run_id": run_id,
        "status": "cancelled",
        "subprocess_signalled": signalled,
    }


@router.get("/songs/{slug}/regen")
def list_runs(slug: str, active_only: bool = Query(default=False), conn=Depends(get_db)):
    song = conn.execute("SELECT id FROM songs WHERE slug = ?", (slug,)).fetchone()
    if not song:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")
    runs = list_song_runs(conn, song["id"], active_only=active_only)
    # Enrich each run with scene_index so the frontend can key regen-in-flight
    # state by the externally-visible scene number. Runs without a scene_id
    # (e.g. stage-level) get scene_index=None.
    scene_id_to_index: dict[int, int] = {}
    scene_ids = {r.scene_id for r in runs if r.scene_id is not None}
    if scene_ids:
        placeholders = ",".join("?" for _ in scene_ids)
        rows = conn.execute(
            f"SELECT id, scene_index FROM scenes WHERE id IN ({placeholders})",
            tuple(scene_ids),
        ).fetchall()
        scene_id_to_index = {row["id"]: row["scene_index"] for row in rows}
    out = []
    for r in runs:
        d = dict(r.__dict__)
        d = _normalize_run_for_response(d)
        d["scene_index"] = (
            scene_id_to_index.get(r.scene_id) if r.scene_id is not None else None
        )
        out.append(d)
    return {"runs": out}


@events_router.get("/events/regen")
async def events(request: Request):
    async def stream():
        # Clients can pass Last-Event-ID to resume; parse if present.
        last_id_header = request.headers.get("Last-Event-ID")
        try:
            last_id = int(last_id_header) if last_id_header else None
        except ValueError:
            last_id = None
        # Initial no-op keepalive so the browser establishes the connection
        yield ": connected\n\n"
        async for ev in hub.subscribe(last_event_id=last_id):
            yield ev.to_sse()
    return StreamingResponse(stream(), media_type="text/event-stream")
