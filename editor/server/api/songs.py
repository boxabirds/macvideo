"""Songs + per-song endpoints.

Routes:
    GET  /api/songs                 list songs with production status
    GET  /api/songs/{slug}          full song + scenes
    PATCH /api/songs/{slug}         update filter / abstraction / quality_mode
    POST /api/import                force a re-scan from music/ + outputs/
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import config as _cfg
from ..generation import run_generation_stage
from ..pipeline.preflight import preflight_stage
from ..importer import import_all
from ..pipeline.transitions import ConflictError, FilterChangeTransition, NotFoundError
from ..rendering import run_render_stage
from ..regen.queue import RegenJob, keyframe_queue
from ..regen.runs import create_run, get_run
from ..store.schema import QualityMode
from ..workflow import evaluate_song_workflow
from .common import get_db, parse_dirty_flags, scene_asset_paths

router = APIRouter()


# ---------- models ----------------------------------------------------------

class StageStatus(BaseModel):
    transcription: Literal["empty", "done", "error"]
    world_brief: Literal["empty", "done", "error"]
    storyboard: Literal["empty", "done", "error"]
    keyframes_done: int
    keyframes_total: int
    clips_done: int
    clips_total: int
    final: Literal["empty", "done"]


class SongSummary(BaseModel):
    slug: str
    audio_path: str
    duration_s: float | None
    size_bytes: int | None
    filter: str | None
    abstraction: int | None
    quality_mode: QualityMode
    status: StageStatus


class SongListResponse(BaseModel):
    songs: list[SongSummary]


class SceneSummary(BaseModel):
    index: int
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


class SongDetailResponse(BaseModel):
    slug: str
    audio_path: str
    duration_s: float | None
    size_bytes: int | None
    filter: str | None
    abstraction: int | None
    quality_mode: QualityMode
    world_brief: str | None
    sequence_arc: str | None
    scenes: list[SceneSummary]
    workflow: dict


class SongPatchBody(BaseModel):
    filter: str | None = Field(default=None)
    abstraction: int | None = Field(default=None, ge=0, le=100)
    quality_mode: QualityMode | None = None
    world_brief: str | None = None


# ---------- helpers ---------------------------------------------------------

def _compute_status(conn, song_id: int) -> StageStatus:
    scene_total = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ?", (song_id,)
    ).fetchone()[0]
    kf_done = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ? AND selected_keyframe_take_id IS NOT NULL",
        (song_id,),
    ).fetchone()[0]
    clip_done = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ? AND selected_clip_take_id IS NOT NULL",
        (song_id,),
    ).fetchone()[0]
    song_row = conn.execute(
        "SELECT world_brief, sequence_arc FROM songs WHERE id = ?", (song_id,)
    ).fetchone()
    storyboard_done = conn.execute(
        "SELECT COUNT(*) FROM scenes WHERE song_id = ? AND beat IS NOT NULL",
        (song_id,),
    ).fetchone()[0] > 0
    final_done = conn.execute(
        "SELECT COUNT(*) FROM finished_videos WHERE song_id = ?", (song_id,)
    ).fetchone()[0] > 0

    return StageStatus(
        transcription="done" if scene_total > 0 else "empty",
        world_brief="done" if song_row and song_row["world_brief"] else "empty",
        storyboard="done" if storyboard_done else "empty",
        keyframes_done=kf_done,
        keyframes_total=scene_total,
        clips_done=clip_done,
        clips_total=scene_total,
        final="done" if final_done else "empty",
    )


# ---------- routes ----------------------------------------------------------

@router.get("/songs", response_model=SongListResponse)
def list_songs(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT id, slug, audio_path, duration_s, size_bytes, filter, abstraction, quality_mode "
        "FROM songs ORDER BY slug"
    ).fetchall()
    songs = [
        SongSummary(
            slug=r["slug"],
            audio_path=r["audio_path"],
            duration_s=r["duration_s"],
            size_bytes=r["size_bytes"],
            filter=r["filter"],
            abstraction=r["abstraction"],
            quality_mode=r["quality_mode"],
            status=_compute_status(conn, r["id"]),
        )
        for r in rows
    ]
    return SongListResponse(songs=songs)


def _fetch_song_row(conn, slug: str):
    row = conn.execute("SELECT * FROM songs WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"song '{slug}' not found")
    return row


@router.get("/songs/{slug}", response_model=SongDetailResponse)
def get_song(slug: str, conn=Depends(get_db)):
    song = _fetch_song_row(conn, slug)
    scenes = conn.execute("""
        SELECT s.*,
               kf.asset_path AS selected_keyframe_path,
               cl.asset_path AS selected_clip_path
        FROM scenes s
        LEFT JOIN takes kf ON kf.id = s.selected_keyframe_take_id
        LEFT JOIN takes cl ON cl.id = s.selected_clip_take_id
        WHERE s.song_id = ?
        ORDER BY s.scene_index
    """, (song["id"],)).fetchall()

    scene_payload: list[SceneSummary] = []
    for r in scenes:
        kf_path, clip_path, missing = scene_asset_paths(r)
        scene_payload.append(SceneSummary(
            index=r["scene_index"],
            kind=r["kind"],
            target_text=r["target_text"],
            start_s=r["start_s"],
            end_s=r["end_s"],
            target_duration_s=r["target_duration_s"],
            num_frames=r["num_frames"],
            beat=r["beat"],
            camera_intent=r["camera_intent"],
            subject_focus=r["subject_focus"],
            prev_link=r["prev_link"],
            next_link=r["next_link"],
            image_prompt=r["image_prompt"],
            prompt_is_user_authored=bool(r["prompt_is_user_authored"]),
            selected_keyframe_path=kf_path,
            selected_clip_path=clip_path,
            missing_assets=missing,
            dirty_flags=parse_dirty_flags(r["dirty_flags"]),
        ))

    workflow = evaluate_song_workflow(conn, song["id"]).to_dict()
    return SongDetailResponse(
        slug=song["slug"],
        audio_path=song["audio_path"],
        duration_s=song["duration_s"],
        size_bytes=song["size_bytes"],
        filter=song["filter"],
        abstraction=song["abstraction"],
        quality_mode=song["quality_mode"],
        world_brief=song["world_brief"],
        sequence_arc=song["sequence_arc"],
        scenes=scene_payload,
        workflow=workflow,
    )


@router.patch("/songs/{slug}", response_model=SongDetailResponse)
def patch_song(slug: str, body: SongPatchBody, conn=Depends(get_db)):
    song = _fetch_song_row(conn, slug)

    patch_fields: dict[str, object] = {}
    if body.filter is not None:
        patch_fields["filter"] = body.filter
    if body.abstraction is not None:
        patch_fields["abstraction"] = body.abstraction
    if body.quality_mode is not None:
        patch_fields["quality_mode"] = body.quality_mode.value
    if body.world_brief is not None:
        patch_fields["world_brief"] = body.world_brief

    if not patch_fields:
        return get_song(slug, conn)

    # Filter changes delegate conflict detection to FilterChangeTransition so
    # no-op filter selections can short-circuit without being blocked by an
    # unrelated active run.
    if "filter" not in patch_fields and any(k in patch_fields for k in ("abstraction", "quality_mode")):
        active = conn.execute("""
            SELECT id FROM regen_runs
            WHERE song_id = ?
              AND status IN ('pending', 'running')
            LIMIT 1
        """, (song["id"],)).fetchone()
        if active:
            raise HTTPException(
                status_code=409,
                detail=f"regeneration run {active['id']} is in progress for this song",
            )

    # Apply non-chain-triggering updates (quality_mode or world_brief).
    non_chain_fields = {k: v for k, v in patch_fields.items() if k not in ("filter", "abstraction")}
    if non_chain_fields:
        sets = ", ".join(f"{k} = ?" for k in non_chain_fields.keys())
        values = list(non_chain_fields.values()) + [time.time(), song["id"]]
        conn.execute(
            f"UPDATE songs SET {sets}, updated_at = ? WHERE id = ?",
            values,
        )

    # Mark clips stale if quality_mode changed (but not if filter/abstraction changes,
    # which do their own clip-stale marking).
    if "quality_mode" in patch_fields and "filter" not in patch_fields and "abstraction" not in patch_fields:
        rows = conn.execute(
            "SELECT id, dirty_flags FROM scenes WHERE song_id = ? "
            "AND selected_clip_take_id IS NOT NULL",
            (song["id"],),
        ).fetchall()
        for r in rows:
            flags = set(parse_dirty_flags(r["dirty_flags"]))
            flags.add("clip_stale")
            conn.execute(
                "UPDATE scenes SET dirty_flags = ?, updated_at = ? WHERE id = ?",
                (json.dumps(sorted(flags)), time.time(), r["id"]),
            )

    # Chain-triggering logic for filter/abstraction changes.
    chain_triggering = "filter" in patch_fields or "abstraction" in patch_fields
    if chain_triggering:
        preflight = preflight_stage(slug=slug, stage="keyframes")
        if not preflight.ok:
            raise HTTPException(status_code=422, detail=preflight.to_http_detail())
        if "filter" in patch_fields:
            new_filter = patch_fields["filter"]
            try:
                transition = FilterChangeTransition(conn, slug, new_filter)
                transition.apply()
            except NotFoundError as e:
                raise HTTPException(status_code=404, detail=str(e)) from e
            except ConflictError as e:
                raise HTTPException(status_code=409, detail=str(e)) from e
            return get_song(slug, conn)
        else:
            # Abstraction change.
            new_abstraction = patch_fields["abstraction"]
            conn.execute(
                "UPDATE songs SET abstraction = ?, updated_at = ? WHERE id = ?",
                (new_abstraction, time.time(), song["id"]),
            )
            scope = "song_abstraction"
            enqueued_filter = song["filter"] or "charcoal"
            enqueued_abstraction = new_abstraction

        # Mark clips stale and null out world_brief/storyboard.
        rows = conn.execute(
            "SELECT id, dirty_flags FROM scenes WHERE song_id = ? "
            "AND selected_clip_take_id IS NOT NULL",
            (song["id"],),
        ).fetchall()
        for r in rows:
            flags = set(parse_dirty_flags(r["dirty_flags"]))
            flags.add("clip_stale")
            conn.execute(
                "UPDATE scenes SET dirty_flags = ?, updated_at = ? WHERE id = ?",
                (json.dumps(sorted(flags)), time.time(), r["id"]),
            )

        conn.execute(
            "UPDATE songs SET world_brief = NULL, sequence_arc = NULL, updated_at = ? "
            "WHERE id = ?", (time.time(), song["id"]),
        )

        # Enqueue the chain job.
        run_id = create_run(conn, scope=scope, song_id=song["id"])
        run = get_run(conn, run_id)
        assert run is not None
        slug_captured = slug
        quality_mode = patch_fields.get("quality_mode", song["quality_mode"]) or "draft"

        async def handler(r):  # noqa: ANN001
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: _run_generation_chain_then_keyframes(
                    slug=slug_captured,
                    source_run_id=r.id,
                    song_filter=enqueued_filter,
                    song_abstraction=enqueued_abstraction,
                    song_quality_mode=quality_mode,
                ),
            )

        keyframe_queue.submit(RegenJob(run=run, handler=handler))

    return get_song(slug, conn)


def _run_generation_chain_then_keyframes(
    *,
    slug: str,
    source_run_id: int,
    song_filter: str,
    song_abstraction: int,
    song_quality_mode: str,
):
    for generation_stage in ("world-brief", "storyboard", "image-prompts"):
        result = run_generation_stage(
            song_slug=slug,
            stage=generation_stage,  # type: ignore[arg-type]
            source_run_id=source_run_id,
        )
        if not result.ok:
            return result
    return run_render_stage(
        song_slug=slug,
        stage="keyframes",
        source_run_id=source_run_id,
    )


@router.post("/import")
def force_import():
    """Scan music/ + outputs/ and import anything new or updated."""
    report = import_all(_cfg.DB_PATH, _cfg.MUSIC_DIR, _cfg.OUTPUTS_DIR)
    return {
        "songs": [
            {
                "slug": r.slug,
                "scenes_imported": r.scenes_imported,
                "keyframe_takes_imported": r.keyframe_takes_imported,
                "clip_takes_imported": r.clip_takes_imported,
                "warnings": r.warnings,
            }
            for r in report.songs
        ],
        "totals": {
            "songs": report.total_songs,
            "scenes": report.total_scenes,
            "keyframe_takes": report.total_keyframe_takes,
            "clip_takes": report.total_clip_takes,
        },
    }
