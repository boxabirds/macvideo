"""Story 9 — HTTP routes for the 5 pipeline stages.
Story 10 — HTTP routes for final-video rendering + finished-video listing.

Stages are strictly ordered; each requires the previous one to be done
(plus filter + abstraction set for world-brief onward).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from ..pipeline.preflight import preflight_stage
from ..generation import run_generation_stage
from ..pipeline.stages import run_gen_keyframes_for_stage
from ..rendering import run_render_stage
from ..regen.queue import RegenJob, keyframe_queue
from ..regen.runs import create_run, get_run
from ..workflow import evaluate_song_workflow
from .common import get_db


router = APIRouter()


StageKey = Literal[
    "transcribe", "world-brief", "storyboard", "image-prompts", "keyframes",
]

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
    workflow = evaluate_song_workflow(conn, song_id)
    stages = workflow.stages
    return {
        "transcribe": {
            "done": stages["transcription"].done,
            "reason": stages["transcription"].blocked_reason or "need a song",
            "ok_to_start": stages["transcription"].state != "blocked",
        },
        "world-brief": _legacy_dep(stages["world_brief"]),
        "storyboard": _legacy_dep(stages["storyboard"]),
        "image-prompts": _legacy_dep(stages["image_prompts"]),
        "keyframes": _legacy_dep(stages["keyframes"]),
    }


def _legacy_dep(stage) -> dict:
    return {
        "done": stage.done,
        "reason": stage.blocked_reason or "This action is not available yet.",
        "ok_to_start": stage.state != "blocked",
        "state": stage.state,
        "can_retry": stage.can_retry,
        "stale_reasons": stage.stale_reasons,
    }


@router.post("/songs/{slug}/stages/{stage}")
async def run_stage(slug: str, stage: str, redo: bool = False, conn=Depends(get_db)):
    if stage not in _STAGE_SCOPES:
        raise HTTPException(status_code=404, detail=f"unknown stage '{stage}'")

    song = conn.execute(
        "SELECT id, quality_mode FROM songs WHERE slug = ?",
        (slug,),
    ).fetchone()
    if not song:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")

    workflow = evaluate_song_workflow(conn, song["id"])
    deps = _stage_deps(conn, song["id"])
    workflow_key = "transcription" if stage == "transcribe" else stage.replace("-", "_")
    action = workflow.stages[workflow_key]  # type: ignore[index]
    if stage != "transcribe" and not action.can_start and not action.can_retry:
        raise HTTPException(status_code=422,
                            detail={"stage": stage, "reason": action.blocked_reason})

    preflight = preflight_stage(slug=slug, stage=stage)  # type: ignore[arg-type]
    if not preflight.ok:
        raise HTTPException(status_code=422, detail=preflight.to_http_detail())

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

    slug_captured = slug
    stage_captured: StageKey = stage  # type: ignore[assignment]
    song_quality_mode = song["quality_mode"]

    async def handler(r):  # noqa: ANN001
        import asyncio
        loop = asyncio.get_event_loop()
        if stage_captured in ("world-brief", "storyboard", "image-prompts"):
            return await loop.run_in_executor(
                None,
                lambda: run_generation_stage(
                    song_slug=slug_captured,
                    stage=stage_captured,  # type: ignore[arg-type]
                    source_run_id=r.id,
                ),
            )
        if stage_captured == "keyframes":
            return await loop.run_in_executor(
                None,
                lambda: run_render_stage(
                    song_slug=slug_captured,
                    stage="keyframes",
                    source_run_id=r.id,
                ),
            )
        return await loop.run_in_executor(
            None,
            lambda: run_gen_keyframes_for_stage(
                song_slug=slug_captured,
                song_filter="",
                song_abstraction=0,
                song_quality_mode=song_quality_mode or "draft",
                source_run_id=r.id,
                stage="transcribe",
                redo=redo,
            ),
        )

    keyframe_queue.submit(RegenJob(run=run, handler=handler))
    return {"run_id": run_id, "status": "pending", "stage": stage}


@router.get("/songs/{slug}/stages")
def list_stages(slug: str, conn=Depends(get_db)):
    song = conn.execute("SELECT id FROM songs WHERE slug = ?", (slug,)).fetchone()
    if not song:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")
    return _stage_deps(conn, song["id"])


@router.post("/songs/{slug}/run-all-stages")
async def run_all_outstanding(slug: str, conn=Depends(get_db)):
    """Run every un-done stage in dependency order. Stops on the first failure.

    Satisfies the PRD 'run all outstanding' clause: one click that advances
    the song through every remaining stage sequentially. Returns the ordered
    list of stages that were triggered + the stage (if any) that stopped the
    chain. The actual stage runs happen via the same keyframe_queue path as
    individual stage triggers, so dependency enforcement + 409 conflicts are
    shared.
    """
    song = conn.execute(
        "SELECT id, quality_mode FROM songs WHERE slug = ?",
        (slug,),
    ).fetchone()
    if not song:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")

    # Refuse if any stage run is already in flight for this song.
    active = conn.execute(
        "SELECT id, scope FROM regen_runs WHERE song_id = ? "
        "AND status IN ('pending', 'running') LIMIT 1",
        (song["id"],),
    ).fetchone()
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"another run is in progress (run {active['id']}, scope {active['scope']})",
        )

    deps = _stage_deps(conn, song["id"])
    workflow = evaluate_song_workflow(conn, song["id"])
    # Transcription still uses the temporary alignment wrapper. Written
    # planning and rendering stages use product services and are queued only
    # when their saved-state prerequisites are already committed.
    slug_captured = slug
    song_quality_mode = song["quality_mode"] or "draft"

    triggered: list[dict] = []
    blocked_at: dict | None = None

    # Transcribe first if needed.
    if not deps["transcribe"]["done"]:
        transcribe_action = workflow.stages["transcription"]
        if not transcribe_action.can_start:
            blocked_at = {"stage": "transcribe", "reason": transcribe_action.blocked_reason}
        else:
            preflight = preflight_stage(slug=slug, stage="transcribe")
            if not preflight.ok:
                blocked_at = {
                    "stage": "transcribe",
                    "reason": preflight.first_reason,
                    "detail": preflight.to_http_detail(),
                }
            else:
                run_id = create_run(conn, scope=_STAGE_SCOPES["transcribe"], song_id=song["id"])
                run = get_run(conn, run_id)
                assert run is not None
                async def transcribe_handler(r):  # noqa: ANN001
                    import asyncio
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(
                        None,
                        lambda: run_gen_keyframes_for_stage(
                            song_slug=slug_captured,
                            song_filter="",
                            song_abstraction=0,
                            song_quality_mode=song_quality_mode,
                            source_run_id=r.id,
                            stage="transcribe",
                            redo=False,
                        ),
                    )
                keyframe_queue.submit(RegenJob(run=run, handler=transcribe_handler))
                triggered.append({"stage": "transcribe", "run_id": run_id})

    # Then queue product generation and rendering stages independently.
    if blocked_at is None:
        for stage_name, workflow_name in (
            ("world-brief", "world_brief"),
            ("storyboard", "storyboard"),
            ("image-prompts", "image_prompts"),
            ("keyframes", "keyframes"),
        ):
            if deps[stage_name]["done"]:  # type: ignore[index]
                continue
            action = workflow.stages[workflow_name]  # type: ignore[index]
            if not action.can_start and not action.can_retry:
                blocked_at = {"stage": stage_name, "reason": action.blocked_reason}
                break
            preflight = preflight_stage(slug=slug, stage=stage_name)  # type: ignore[arg-type]
            if not preflight.ok:
                blocked_at = {
                    "stage": stage_name,
                    "reason": preflight.first_reason,
                    "detail": preflight.to_http_detail(),
                }
                break
            run_id = create_run(conn, scope=_STAGE_SCOPES[stage_name], song_id=song["id"])  # type: ignore[index]
            run = get_run(conn, run_id)
            assert run is not None
            stage_captured = stage_name
            async def chain_handler(r, stage_captured=stage_captured):  # noqa: ANN001
                import asyncio
                loop = asyncio.get_event_loop()
                if stage_captured in ("world-brief", "storyboard", "image-prompts"):
                    return await loop.run_in_executor(
                        None,
                        lambda: run_generation_stage(
                            song_slug=slug_captured,
                            stage=stage_captured,  # type: ignore[arg-type]
                            source_run_id=r.id,
                        ),
                    )
                if stage_captured == "keyframes":
                    return await loop.run_in_executor(
                        None,
                        lambda: run_render_stage(
                            song_slug=slug_captured,
                            stage="keyframes",
                            source_run_id=r.id,
                        ),
                    )
                raise RuntimeError(f"unsupported product stage {stage_captured}")
            keyframe_queue.submit(RegenJob(run=run, handler=chain_handler))
            triggered.append({"stage": stage_name, "run_id": run_id})
            if stage_name != "world-brief":
                continue
            # Later stages depend on the new world text, so a second call to
            # run-all will continue the chain after this background run commits.
            break

    return {
        "triggered": triggered,
        "blocked_at": blocked_at,
    }


# ---------- story 10: final render -----------------------------------------

@router.post("/songs/{slug}/render-final")
async def render_final_route(slug: str, conn=Depends(get_db)):
    song = conn.execute(
        "SELECT id, quality_mode FROM songs WHERE slug = ?", (slug,),
    ).fetchone()
    if not song:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")

    missing_clips = conn.execute("""
        SELECT scene_index FROM scenes
        WHERE song_id = ? AND selected_clip_take_id IS NULL
        ORDER BY scene_index
    """, (song["id"],)).fetchall()
    if missing_clips:
        raise HTTPException(status_code=422, detail={
            "reason": "missing clip takes",
            "affected_scenes": [r["scene_index"] for r in missing_clips],
        })

    preflight = preflight_stage(slug=slug, stage="final-video")
    if not preflight.ok:
        raise HTTPException(status_code=422, detail=preflight.to_http_detail())

    conflict = conn.execute(
        "SELECT id FROM regen_runs WHERE song_id = ? AND scope = 'final_video' "
        "AND status IN ('pending', 'running') LIMIT 1", (song["id"],),
    ).fetchone()
    if conflict:
        raise HTTPException(status_code=409,
                            detail=f"final render already running (run {conflict['id']})")

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
    slug_captured = slug

    async def handler(r):  # noqa: ANN001
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: run_render_stage(
                song_slug=slug_captured,
                stage="final-video",
                source_run_id=r.id,
            ),
        )

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
