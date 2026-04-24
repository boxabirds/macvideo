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
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import config as _cfg
from ..regen.events import hub
from ..regen.queue import clip_queue, keyframe_queue, RegenJob
from ..regen.runs import (
    RegenRun,
    create_run,
    get_run,
    list_song_runs,
    update_run_status,
)
from ..regen.stub_handlers import stub_clip_handler, stub_keyframe_handler
from .common import get_db


router = APIRouter()
events_router = APIRouter()


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
        SELECT s.id AS scene_id, s.image_prompt, g.id AS song_id, g.quality_mode
        FROM scenes s JOIN songs g ON g.id = s.song_id
        WHERE g.slug = ? AND s.scene_index = ?
    """, (slug, idx)).fetchone()
    if row is None:
        raise HTTPException(status_code=404,
                            detail=f"scene {idx} of song '{slug}' not found")

    # 409 if another regen of the same (scene, artefact_kind) is pending/running
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

    # Pick the right queue + handler. Stub handlers for now; real subprocess
    # wrappers go here when the pipeline integration lands.
    if body.artefact_kind == "keyframe":
        handler = lambda r: stub_keyframe_handler(r, db_path=_cfg.DB_PATH)  # noqa: E731
        queue = keyframe_queue
        estimate = 15
    else:
        handler = lambda r: stub_clip_handler(r, db_path=_cfg.DB_PATH)  # noqa: E731
        queue = clip_queue
        estimate = 1200 if quality_mode == "final" else 120

    queue.submit(RegenJob(run=run, handler=handler))

    return TakeTriggerResponse(run_id=run_id, status="pending", estimated_seconds=estimate)


@router.post("/regen/{run_id}/cancel")
async def cancel_run(run_id: int, conn=Depends(get_db)):
    run = get_run(conn, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=409,
                            detail=f"run {run_id} already in terminal state '{run.status}'")
    update_run_status(conn, run_id, "cancelled")
    # Real cancellation would SIGTERM the subprocess; for the stub we just flip state.
    return {"run_id": run_id, "status": "cancelled"}


@router.get("/songs/{slug}/regen")
def list_runs(slug: str, active_only: bool = Query(default=False), conn=Depends(get_db)):
    song = conn.execute("SELECT id FROM songs WHERE slug = ?", (slug,)).fetchone()
    if not song:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")
    runs = list_song_runs(conn, song["id"], active_only=active_only)
    return {"runs": [r.__dict__ for r in runs]}


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
