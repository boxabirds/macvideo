"""Per-scene routes: GET + PATCH edit-in-place."""

from __future__ import annotations

import json
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from ..store.staleness import (
    IDENTITY_REF_WINDOW,
    SceneFieldEdit,
    flags_after_scene_edit,
)
from .common import get_db, parse_dirty_flags, scene_asset_paths


router = APIRouter()


# Product camera-intent vocabulary consumed by render adapters.
CAMERA_INTENTS = [
    "static hold",
    "slow push in",
    "slow pull back",
    "pan left",
    "pan right",
    "tilt up",
    "tilt down",
    "orbit left",
    "orbit right",
    "handheld drift",
    "held on detail",
]


class ScenePatchBody(BaseModel):
    beat: str | None = None
    camera_intent: str | None = None
    subject_focus: str | None = None
    image_prompt: str | None = None
    # target_text edits are a deliberate widening of the Story 3 PRD (which
    # marks target_text as read-only because it originates in WhisperX). The
    # user explicitly requested the ability to override the aligned lyric at
    # the frontend level, so this field participates in the same
    # staleness-cascade rules as beat/subject_focus (keyframe_stale +
    # clip_stale on this scene plus keyframe_stale on N+1..N+4).
    target_text: str | None = None
    # POST-style actions via PATCH; see tests. Leave empty to no-op the flag.
    prompt_is_user_authored: bool | None = None
    selection_pinned: bool | None = None
    selected_keyframe_take_id: int | None = None
    selected_clip_take_id: int | None = None

    @model_validator(mode="after")
    def _validate_camera_intent(self):
        if self.camera_intent is not None and self.camera_intent not in CAMERA_INTENTS:
            raise ValueError(
                f"camera_intent must be one of: {', '.join(CAMERA_INTENTS)}"
            )
        return self


class SceneResponse(BaseModel):
    index: int
    song_slug: str
    kind: str
    target_text: str
    start_s: float
    end_s: float
    target_duration_s: float
    num_frames: int
    beat: str | None
    camera_intent: str | None
    subject_focus: str | None
    prev_link: str | None
    next_link: str | None
    image_prompt: str | None
    prompt_is_user_authored: bool
    selected_keyframe_path: str | None
    selected_clip_path: str | None
    missing_assets: list[str]
    dirty_flags: list[str]


def _scene_row_to_response(row) -> SceneResponse:
    kf_path, clip_path, missing = scene_asset_paths(row)
    return SceneResponse(
        index=row["scene_index"],
        song_slug=row["song_slug"],
        kind=row["kind"],
        target_text=row["target_text"],
        start_s=row["start_s"],
        end_s=row["end_s"],
        target_duration_s=row["target_duration_s"],
        num_frames=row["num_frames"],
        beat=row["beat"],
        camera_intent=row["camera_intent"],
        subject_focus=row["subject_focus"],
        prev_link=row["prev_link"],
        next_link=row["next_link"],
        image_prompt=row["image_prompt"],
        prompt_is_user_authored=bool(row["prompt_is_user_authored"]),
        selected_keyframe_path=kf_path,
        selected_clip_path=clip_path,
        missing_assets=missing,
        dirty_flags=parse_dirty_flags(row["dirty_flags"]),
    )


def _fetch_scene(conn, slug: str, idx: int):
    row = conn.execute("""
        SELECT s.*, g.slug AS song_slug,
               kf.asset_path AS selected_keyframe_path,
               cl.asset_path AS selected_clip_path
        FROM scenes s
        JOIN songs g ON g.id = s.song_id
        LEFT JOIN takes kf ON kf.id = s.selected_keyframe_take_id
        LEFT JOIN takes cl ON cl.id = s.selected_clip_take_id
        WHERE g.slug = ? AND s.scene_index = ?
    """, (slug, idx)).fetchone()
    if row is None:
        raise HTTPException(status_code=404,
                            detail=f"scene {idx} of song '{slug}' not found")
    return row


@router.get("/songs/{slug}/scenes/{idx}", response_model=SceneResponse)
def get_scene(slug: str, idx: int, conn=Depends(get_db)):
    return _scene_row_to_response(_fetch_scene(conn, slug, idx))


def _scene_count(conn, song_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ?", (song_id,)
    ).fetchone()[0]


@router.patch("/songs/{slug}/scenes/{idx}", response_model=SceneResponse)
def patch_scene(slug: str, idx: int, body: ScenePatchBody, conn=Depends(get_db)):
    existing = _fetch_scene(conn, slug, idx)

    patch_fields: dict[str, object] = {}
    changed_editable: list[str] = []
    for field_name in (
        "beat", "camera_intent", "subject_focus", "image_prompt", "target_text",
    ):
        new_val = getattr(body, field_name)
        if new_val is None:
            continue
        if existing[field_name] != new_val:
            patch_fields[field_name] = new_val
            changed_editable.append(field_name)

    # Image-prompt edit flips the user-authored flag on unless the body
    # explicitly sets it to False (e.g., 'reset to generated').
    if "image_prompt" in patch_fields and body.prompt_is_user_authored is not False:
        patch_fields["prompt_is_user_authored"] = 1
    elif body.prompt_is_user_authored is not None:
        patch_fields["prompt_is_user_authored"] = 1 if body.prompt_is_user_authored else 0

    # Take selection overrides
    for field_name in ("selected_keyframe_take_id", "selected_clip_take_id"):
        v = getattr(body, field_name)
        if v is not None:
            patch_fields[field_name] = v
    if body.selection_pinned is not None:
        patch_fields["selection_pinned"] = 1 if body.selection_pinned else 0

    if not patch_fields:
        return _scene_row_to_response(existing)

    # Apply staleness rules for each editable field that changed
    current_flags = parse_dirty_flags(existing["dirty_flags"])
    neighbour_updates: dict[int, set[str]] = {}
    for field_name in changed_editable:
        edit = SceneFieldEdit(scene_index=idx, field_name=field_name)
        current_flags_set, neighbours = flags_after_scene_edit(
            current_flags, edit, _scene_count(conn, existing["song_id"]),
        )
        current_flags = list(current_flags_set)
        for nb_idx, nb_flags in neighbours.items():
            neighbour_updates.setdefault(nb_idx, set()).update(nb_flags)

    patch_fields["dirty_flags"] = json.dumps(sorted(set(current_flags)))

    # Apply primary scene update
    sets = ", ".join(f"{k} = ?" for k in patch_fields.keys())
    values = list(patch_fields.values()) + [time.time(), existing["id"]]
    conn.execute(
        f"UPDATE scenes SET {sets}, updated_at = ? WHERE id = ?",
        values,
    )

    # Cascade identity-chain neighbour updates
    for nb_idx, nb_flags_set in neighbour_updates.items():
        nb_row = conn.execute(
            "SELECT id, dirty_flags FROM scenes WHERE song_id = ? AND scene_index = ?",
            (existing["song_id"], nb_idx),
        ).fetchone()
        if nb_row is None:
            continue
        nb_flags = set(parse_dirty_flags(nb_row["dirty_flags"]))
        nb_flags.update(nb_flags_set)
        conn.execute(
            "UPDATE scenes SET dirty_flags = ?, updated_at = ? WHERE id = ?",
            (json.dumps(sorted(nb_flags)), time.time(), nb_row["id"]),
        )

    return _scene_row_to_response(_fetch_scene(conn, slug, idx))


@router.get("/camera-intents")
def list_camera_intents():
    """Allowed vocabulary for camera_intent (used by the frontend dropdown)."""
    return {"values": CAMERA_INTENTS}


@router.get("/songs/{slug}/scenes/{idx}/takes")
def list_scene_takes(slug: str, idx: int, conn=Depends(get_db)):
    """All takes for a scene (keyframes + clips), most recent first. Used
    by the story 5 TakePicker to let the user compare and pick."""
    row = _fetch_scene(conn, slug, idx)
    takes = conn.execute("""
        SELECT id, artefact_kind, asset_path, created_at, quality_mode,
               source_run_id, prompt_snapshot
        FROM takes WHERE scene_id = ?
        ORDER BY created_at DESC
    """, (row["id"],)).fetchall()

    selected = {
        "keyframe": row["selected_keyframe_take_id"],
        "clip": row["selected_clip_take_id"],
    }
    return {
        "takes": [
            {
                "id": t["id"],
                "artefact_kind": t["artefact_kind"],
                "asset_path": t["asset_path"],
                "created_at": t["created_at"],
                "quality_mode": t["quality_mode"],
                "source_run_id": t["source_run_id"],
                "is_selected": t["id"] == selected.get(t["artefact_kind"]),
            }
            for t in takes
        ],
    }
