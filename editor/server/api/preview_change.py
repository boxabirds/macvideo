"""Story 4 — POST /api/songs/:slug/preview-change.

Pure read-only endpoint that returns the scope + cost + time estimate for a
proposed filter or abstraction change. Used by the frontend's
FilterChangeModal before the user confirms the destructive PATCH. Does NOT
mutate any state.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from ..pipeline.pricing import estimate_filter_change
from .common import get_db


router = APIRouter()


class PreviewChangeBody(BaseModel):
    filter: Optional[str] = None
    abstraction: Optional[int] = None

    @model_validator(mode="after")
    def _exactly_one(self):
        n = sum(v is not None for v in (self.filter, self.abstraction))
        if n != 1:
            raise ValueError("exactly one of filter|abstraction must be set")
        return self


@router.post("/songs/{slug}/preview-change")
def preview_change(slug: str, body: PreviewChangeBody, conn=Depends(get_db)):
    song = conn.execute(
        "SELECT id, filter, abstraction FROM songs WHERE slug = ?", (slug,),
    ).fetchone()
    if not song:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")

    scene_count = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ?", (song["id"],),
    ).fetchone()[0]
    user_authored = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ? AND prompt_is_user_authored = 1",
        (song["id"],),
    ).fetchone()[0]
    clip_count = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ? AND selected_clip_take_id IS NOT NULL",
        (song["id"],),
    ).fetchone()[0]

    active = conn.execute(
        "SELECT id FROM regen_runs WHERE song_id = ? "
        "AND scope IN ('song_filter','song_abstraction','stage_keyframes','stage_image_prompts') "
        "AND status IN ('pending','running') LIMIT 1",
        (song["id"],),
    ).fetchone()

    est = estimate_filter_change(
        scene_count=scene_count,
        user_authored_count=user_authored,
        clip_count=clip_count,
    )

    return {
        "from": {"filter": song["filter"], "abstraction": song["abstraction"]},
        "to": {"filter": body.filter, "abstraction": body.abstraction},
        "scope": {
            "will_regen_world_brief": est.will_regen_world_brief,
            "will_regen_storyboard": est.will_regen_storyboard,
            "scenes_with_new_prompts": est.scenes_with_new_prompts,
            "keyframes_to_generate": est.keyframes_to_generate,
            "clips_marked_stale": est.clips_marked_stale,
            "clips_deleted": 0,
        },
        "estimate": {
            "gemini_calls": est.gemini_calls,
            "estimated_usd": est.estimated_usd,
            "estimated_seconds": est.estimated_seconds,
            "confidence": est.confidence,
        },
        "would_conflict_with": (
            {"run_id": active["id"], "reason": "a chain is already running for this song"}
            if active else None
        ),
    }
