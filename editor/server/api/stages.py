"""Story 9 — HTTP routes for the 5 pipeline stages.
Story 10 — HTTP routes for final-video rendering + finished-video listing.

Stages are strictly ordered; each requires the previous one to be done
(plus filter + abstraction set for world-brief onward).
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from .. import config as _cfg
from ..regen.queue import RegenJob, keyframe_queue
from ..regen.runs import create_run, get_run
from ..regen.stages import (
    stub_final_render,
    stub_image_prompts,
    stub_keyframes,
    stub_storyboard,
    stub_transcribe,
    stub_world_brief,
)
from .common import get_db


router = APIRouter()


StageKey = Literal[
    "transcribe", "world-brief", "storyboard", "image-prompts", "keyframes",
]

_STAGE_HANDLERS = {
    "transcribe":     stub_transcribe,
    "world-brief":    stub_world_brief,
    "storyboard":     stub_storyboard,
    "image-prompts":  stub_image_prompts,
    # keyframes needs source_run_id bound, so the handler is wrapped below.
}

_STAGE_SCOPES = {
    "transcribe":     "stage_transcribe",
    "world-brief":    "stage_world_brief",
    "storyboard":     "stage_storyboard",
    "image-prompts":  "stage_image_prompts",
    "keyframes":      "stage_keyframes",
}


def _stage_deps(conn, song_id: int) -> dict[StageKey, dict]:
    """Compute stage state for a song: each stage's status + whether its
    upstream prerequisite is met."""
    song = conn.execute(
        "SELECT filter, abstraction, world_brief, sequence_arc FROM songs WHERE id = ?",
        (song_id,),
    ).fetchone()
    total_scenes = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ?", (song_id,),
    ).fetchone()[0]
    with_beat = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ? AND beat IS NOT NULL", (song_id,),
    ).fetchone()[0]
    with_prompt = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ? AND image_prompt IS NOT NULL",
        (song_id,),
    ).fetchone()[0]
    with_kf = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ? AND selected_keyframe_take_id IS NOT NULL",
        (song_id,),
    ).fetchone()[0]
    return {
        "transcribe": {"done": total_scenes > 0, "reason": "need a song"},
        "world-brief": {
            "done": bool(song["world_brief"]),
            "reason": "need transcribe done, filter + abstraction set",
            "ok_to_start": total_scenes > 0 and song["filter"] is not None and song["abstraction"] is not None,
        },
        "storyboard": {
            "done": bool(song["sequence_arc"]),
            "reason": "need world-brief done",
            "ok_to_start": bool(song["world_brief"]),
        },
        "image-prompts": {
            "done": with_prompt == total_scenes and total_scenes > 0,
            "reason": "need storyboard done",
            "ok_to_start": with_beat > 0,
        },
        "keyframes": {
            "done": with_kf == total_scenes and total_scenes > 0,
            "reason": "need image-prompts done",
            "ok_to_start": with_prompt > 0,
        },
    }


@router.post("/songs/{slug}/stages/{stage}")
async def run_stage(slug: str, stage: str, conn=Depends(get_db)):
    if stage not in _STAGE_SCOPES:
        raise HTTPException(status_code=404, detail=f"unknown stage '{stage}'")

    song = conn.execute("SELECT id, filter, abstraction FROM songs WHERE slug = ?",
                        (slug,)).fetchone()
    if not song:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")

    deps = _stage_deps(conn, song["id"])
    if stage != "transcribe" and not deps[stage].get("ok_to_start"):
        raise HTTPException(status_code=422,
                            detail={"stage": stage, "reason": deps[stage]["reason"]})

    # 409 if a run of the same scope already in flight
    conflict = conn.execute(
        "SELECT id FROM regen_runs WHERE song_id = ? AND scope = ? "
        "AND status IN ('pending', 'running') LIMIT 1",
        (song["id"], _STAGE_SCOPES[stage]),
    ).fetchone()
    if conflict:
        raise HTTPException(status_code=409,
                            detail=f"stage '{stage}' already running (run {conflict['id']})")

    run_id = create_run(conn, scope=_STAGE_SCOPES[stage], song_id=song["id"])
    run = get_run(conn, run_id)
    assert run is not None

    if stage == "keyframes":
        async def kf_handler(r):  # noqa: ANN001
            await stub_keyframes(song["id"], db_path=_cfg.DB_PATH, source_run_id=r.id)
        keyframe_queue.submit(RegenJob(run=run, handler=kf_handler))
    else:
        handler_fn = _STAGE_HANDLERS[stage]
        async def handler(r):  # noqa: ANN001
            await handler_fn(song["id"], db_path=_cfg.DB_PATH)
        keyframe_queue.submit(RegenJob(run=run, handler=handler))

    return {"run_id": run_id, "status": "pending", "stage": stage}


@router.get("/songs/{slug}/stages")
def list_stages(slug: str, conn=Depends(get_db)):
    song = conn.execute("SELECT id FROM songs WHERE slug = ?", (slug,)).fetchone()
    if not song:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")
    return _stage_deps(conn, song["id"])


# ---------- story 10: final render -----------------------------------------

@router.post("/songs/{slug}/render-final")
async def render_final(slug: str, conn=Depends(get_db)):
    song = conn.execute("SELECT id, quality_mode FROM songs WHERE slug = ?",
                        (slug,)).fetchone()
    if not song:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")

    # Pre-flight: every scene must have a selected keyframe
    missing_kf = conn.execute("""
        SELECT scene_index FROM scenes
        WHERE song_id = ? AND selected_keyframe_take_id IS NULL
        ORDER BY scene_index
    """, (song["id"],)).fetchall()
    if missing_kf:
        raise HTTPException(status_code=422, detail={
            "reason": "missing keyframe takes",
            "affected_scenes": [r["scene_index"] for r in missing_kf],
        })

    conflict = conn.execute(
        "SELECT id FROM regen_runs WHERE song_id = ? AND scope = 'final_video' "
        "AND status IN ('pending', 'running') LIMIT 1", (song["id"],),
    ).fetchone()
    if conflict:
        raise HTTPException(status_code=409,
                            detail=f"final render already running (run {conflict['id']})")

    # Count clips to render vs reuse, for the UI estimate
    need = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ? AND selected_clip_take_id IS NULL",
        (song["id"],),
    ).fetchone()[0]
    total = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ?", (song["id"],),
    ).fetchone()[0]

    run_id = create_run(
        conn, scope="final_video", song_id=song["id"],
        quality_mode=song["quality_mode"],
    )
    run = get_run(conn, run_id)
    assert run is not None

    async def handler(r):  # noqa: ANN001
        await stub_final_render(song["id"], db_path=_cfg.DB_PATH, source_run_id=r.id)

    keyframe_queue.submit(RegenJob(run=run, handler=handler))

    return {
        "run_id": run_id,
        "status": "pending",
        "clips_to_render": need,
        "clips_reusable": total - need,
    }


@router.get("/songs/{slug}/finished")
def list_finished(slug: str, conn=Depends(get_db)):
    song = conn.execute("SELECT id FROM songs WHERE slug = ?", (slug,)).fetchone()
    if not song:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")
    rows = conn.execute(
        "SELECT * FROM finished_videos WHERE song_id = ? ORDER BY created_at DESC",
        (song["id"],),
    ).fetchall()
    return {"finished": [dict(r) for r in rows]}
