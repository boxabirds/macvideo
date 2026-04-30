"""Story 4 — POST /api/songs/:slug/preview-change.

Pure read-only endpoint that returns the scope + cost + time estimate for a
proposed filter or abstraction change. Used by the frontend's
FilterChangeModal before the user confirms the destructive PATCH. Does NOT
mutate any state.

Delegates to FilterChangeTransition for kind classification and preview
computation, ensuring parity with the PATCH handler.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from ..pipeline.transitions import FilterChangeTransition
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
    # Validate song exists.
    song = conn.execute(
        "SELECT id FROM songs WHERE slug = ?", (slug,),
    ).fetchone()
    if not song:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")

    # Filter changes are the only ones supported by FilterChangeTransition.
    # Abstraction changes follow the same rules but are not yet consolidated.
    if body.filter is not None:
        transition = FilterChangeTransition(conn, slug, body.filter)
        return transition.preview()

    # TODO: Story 11.2b — consolidate abstraction change logic into
    # FilterChangeTransition (parallels filter contract).
    raise HTTPException(
        status_code=501,
        detail="abstraction preview not yet refactored to use transitions module",
    )
