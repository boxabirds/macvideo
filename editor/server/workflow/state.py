"""Central workflow state evaluation for song-level product actions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

from ..pipeline.preflight import preflight_stage


StageKey = Literal[
    "transcription",
    "world_brief",
    "storyboard",
    "image_prompts",
    "keyframes",
    "final_video",
]

ActionState = Literal[
    "done",
    "available",
    "blocked",
    "running",
    "retryable",
    "stale",
]


@dataclass(frozen=True)
class StageDef:
    key: StageKey
    label: str
    stage_name: str
    scope: str
    prereqs: tuple[StageKey, ...]
    history_model: Literal["replace", "take"]


@dataclass(frozen=True)
class RunRef:
    id: int
    scope: str
    status: str
    error: str | None
    progress_pct: int | None
    phase: str | None
    started_at: float | None
    ended_at: float | None
    created_at: float


@dataclass(frozen=True)
class StageProgressView:
    operation: str
    detail: str | None
    progress_pct: int | None
    processed_seconds: float | None
    total_seconds: float | None


@dataclass(frozen=True)
class StageWorkflowView:
    key: StageKey
    label: str
    stage_name: str
    scope: str
    history_model: str
    state: ActionState
    done: bool
    available: bool
    can_start: bool
    can_retry: bool
    blocked_reason: str | None
    failed_reason: str | None
    stale_reasons: list[str]
    invalidates: list[StageKey]
    summary: str
    active_run: RunRef | None
    failed_run: RunRef | None
    progress: StageProgressView | None


@dataclass(frozen=True)
class SongWorkflowView:
    stages: dict[StageKey, StageWorkflowView]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stages": {
                key: asdict(stage)
                for key, stage in self.stages.items()
            },
        }


STAGE_DEFS: tuple[StageDef, ...] = (
    StageDef("transcription", "transcription", "transcribe", "stage_transcribe", (), "replace"),
    StageDef("world_brief", "world description", "world-brief", "stage_world_brief", ("transcription",), "replace"),
    StageDef("storyboard", "storyboard", "storyboard", "stage_storyboard", ("world_brief",), "replace"),
    StageDef("image_prompts", "image prompts", "image-prompts", "stage_image_prompts", ("storyboard",), "replace"),
    StageDef("keyframes", "keyframes", "keyframes", "stage_keyframes", ("image_prompts",), "take"),
    StageDef("final_video", "final video", "render-final", "final_video", ("keyframes",), "replace"),
)

_BY_KEY = {stage.key: stage for stage in STAGE_DEFS}

_AUDIO_TRANSCRIBE_PHASE_LABELS = {
    "separating-vocals": "Separating vocals",
    "transcribing": "Transcribing",
    "aligning": "Aligning timings",
}

_OPERATION_BY_STAGE = {
    "transcription": "Lyric transcription",
    "world_brief": "Generating world description",
    "storyboard": "Generating storyboard",
    "image_prompts": "Generating image prompts",
    "keyframes": "Creating keyframes",
    "final_video": "Rendering final video",
}

_SCOPE_TO_KEY = {
    "stage_transcribe": "transcription",
    "stage_audio_transcribe": "transcription",
    "stage_world_brief": "world_brief",
    "stage_storyboard": "storyboard",
    "stage_image_prompts": "image_prompts",
    "stage_keyframes": "keyframes",
    "song_filter": "world_brief",
    "song_abstraction": "world_brief",
    "final_video": "final_video",
}


def _run_ref(row: Any) -> RunRef:
    return RunRef(
        id=row["id"],
        scope=row["scope"],
        status=row["status"],
        error=row["error"],
        progress_pct=row["progress_pct"],
        phase=row["phase"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        created_at=row["created_at"],
    )


def _stage_for_run(stage: StageDef, run: RunRef) -> bool:
    if stage.key == "transcription":
        return run.scope in ("stage_transcribe", "stage_audio_transcribe")
    return _SCOPE_TO_KEY.get(run.scope) == stage.key


def _dirty_flags(raw: str | None) -> set[str]:
    if not raw:
        return set()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    return {str(item) for item in value if isinstance(item, str)}


def _block_reason(stage: StageDef, prereq_labels: list[str], *, has_filter: bool, has_abstraction: bool) -> str:
    if prereq_labels and prereq_labels[0] == "transcription":
        return "Complete transcription first."
    if stage.key == "world_brief" and (not has_filter or not has_abstraction):
        return "Choose a filter and abstraction first."
    if stage.key in ("image_prompts", "keyframes", "final_video") and (
        "world description" in prereq_labels or "storyboard" in prereq_labels
    ):
        return "Please generate the world and storyboard first."
    if prereq_labels:
        return f"Complete {', '.join(prereq_labels)} first."
    return "This action is not available yet."


def _summary_for(stage: StageDef, *, done_count: int, total_count: int) -> str:
    if stage.key in ("image_prompts", "keyframes"):
        return f" ({done_count}/{total_count})"
    return ""


def describe_stage_progress(stage_key: str, run: RunRef | None, *, duration_s: float | None = None) -> StageProgressView | None:
    """Return display-safe progress for an active run.

    Missing runs return None so the UI does not invent a misleading operation.
    """
    if run is None or run.status not in ("pending", "running"):
        return None

    pct = run.progress_pct
    processed = None
    total = None
    detail = None

    if stage_key == "transcription" and run.scope == "stage_audio_transcribe":
        operation = _AUDIO_TRANSCRIBE_PHASE_LABELS.get(run.phase or "", "Preparing transcription")
        if run.phase == "transcribing" and pct is not None and duration_s:
            bounded_pct = max(0, min(100, pct))
            processed = duration_s * bounded_pct / 100
            total = duration_s
            detail = "audio time processed"
        return StageProgressView(operation, detail, pct, processed, total)

    if stage_key == "transcription":
        return StageProgressView("Aligning lyrics", None, pct, None, duration_s)

    operation = _OPERATION_BY_STAGE.get(stage_key, "Running")
    return StageProgressView(operation, None, pct, None, None)


def evaluate_song_workflow(conn, song_id: int) -> SongWorkflowView:
    song = conn.execute(
        "SELECT id, slug, filter, abstraction, world_brief, sequence_arc, duration_s "
        "FROM songs WHERE id = ?",
        (song_id,),
    ).fetchone()
    if song is None:
        raise ValueError(f"song {song_id} not found")

    scenes = conn.execute(
        "SELECT dirty_flags, beat, image_prompt, selected_keyframe_take_id, selected_clip_take_id "
        "FROM scenes WHERE song_id = ? ORDER BY scene_index",
        (song_id,),
    ).fetchall()
    runs = [
        _run_ref(row)
        for row in conn.execute(
            "SELECT * FROM regen_runs WHERE song_id = ? ORDER BY created_at DESC, id DESC LIMIT 200",
            (song_id,),
        ).fetchall()
    ]
    finished_count = conn.execute(
        "SELECT COUNT(*) FROM finished_videos WHERE song_id = ?",
        (song_id,),
    ).fetchone()[0]

    total = len(scenes)
    with_beat = sum(1 for scene in scenes if scene["beat"])
    with_prompt = sum(1 for scene in scenes if scene["image_prompt"])
    with_keyframe = sum(1 for scene in scenes if scene["selected_keyframe_take_id"] is not None)
    with_clip = sum(1 for scene in scenes if scene["selected_clip_take_id"] is not None)
    flags = [_dirty_flags(scene["dirty_flags"]) for scene in scenes]
    has_keyframe_stale = any("keyframe_stale" in scene_flags for scene_flags in flags)
    has_clip_stale = any("clip_stale" in scene_flags for scene_flags in flags)

    done_by_key = {
        "transcription": total > 0,
        "world_brief": bool(song["world_brief"]),
        "storyboard": bool(song["sequence_arc"]),
        "image_prompts": total > 0 and with_prompt == total,
        "keyframes": total > 0 and with_keyframe == total and not has_keyframe_stale,
        "final_video": finished_count > 0 and not has_clip_stale,
    }
    stale_reasons_by_key: dict[StageKey, list[str]] = {
        "transcription": [],
        "world_brief": [],
        "storyboard": [],
        "image_prompts": [],
        "keyframes": ["Scene prompts changed; regenerate stale keyframes."] if has_keyframe_stale and with_keyframe > 0 else [],
        "final_video": ["Selected clips are stale; render the final video again."] if has_clip_stale and with_clip > 0 else [],
    }
    count_by_key = {
        "image_prompts": with_prompt,
        "keyframes": with_keyframe,
    }

    stages: dict[StageKey, StageWorkflowView] = {}
    for stage in STAGE_DEFS:
        stage_runs = [run for run in runs if _stage_for_run(stage, run)]
        active_run = next((run for run in stage_runs if run.status in ("pending", "running")), None)
        terminal_run = next((run for run in stage_runs if run.status in ("done", "failed", "cancelled")), None)
        failed_run = terminal_run if terminal_run and terminal_run.status == "failed" else None
        prereq_labels = [
            _BY_KEY[prereq].label
            for prereq in stage.prereqs
            if prereq in stages and stages[prereq].state != "done"
        ]
        if stage.key == "world_brief":
            if song["filter"] is None:
                prereq_labels.append("filter")
            if song["abstraction"] is None:
                prereq_labels.append("abstraction")
        if stage.key == "final_video" and total > 0 and with_clip < total:
            prereq_labels.append("scene clips")

        done = done_by_key[stage.key]
        stale_reasons = stale_reasons_by_key[stage.key]
        state: ActionState
        if active_run:
            state = "running"
        elif failed_run:
            state = "retryable"
        elif stale_reasons:
            state = "stale"
        elif done:
            state = "done"
        elif prereq_labels:
            state = "blocked"
        else:
            if stage.key in ("world_brief", "storyboard", "image_prompts", "keyframes", "final_video"):
                preflight_stage_name = "final-video" if stage.key == "final_video" else stage.stage_name
                preflight = preflight_stage(slug=song["slug"], stage=preflight_stage_name)  # type: ignore[arg-type]
                state = "available" if preflight.ok else "blocked"
            else:
                state = "available"

        blocked_reason = None
        if state == "blocked":
            if not prereq_labels:
                preflight_stage_name = "final-video" if stage.key == "final_video" else stage.stage_name
                preflight = preflight_stage(slug=song["slug"], stage=preflight_stage_name)  # type: ignore[arg-type]
                blocked_reason = preflight.first_reason or "This action is not available yet."
            elif stage.key == "final_video" and "scene clips" in prereq_labels:
                blocked_reason = "Render clips for every scene first."
            elif stage.key in ("image_prompts", "keyframes", "final_video") and (
                not stages.get("world_brief") or stages["world_brief"].state != "done"
                or not stages.get("storyboard") or stages["storyboard"].state != "done"
            ):
                blocked_reason = "Please generate the world and storyboard first."
            else:
                blocked_reason = _block_reason(
                    stage,
                    prereq_labels,
                    has_filter=song["filter"] is not None,
                    has_abstraction=song["abstraction"] is not None,
                )

        progress = describe_stage_progress(stage.key, active_run, duration_s=song["duration_s"])
        stages[stage.key] = StageWorkflowView(
            key=stage.key,
            label=stage.label,
            stage_name=stage.stage_name,
            scope=stage.scope,
            history_model=stage.history_model,
            state=state,
            done=done,
            available=state in ("available", "done", "retryable", "stale"),
            can_start=state in ("available", "done", "stale"),
            can_retry=state == "retryable",
            blocked_reason=blocked_reason,
            failed_reason=failed_run.error if failed_run else None,
            stale_reasons=stale_reasons,
            invalidates=list(_invalidates(stage.key)),
            summary=_summary_for(
                stage,
                done_count=count_by_key.get(stage.key, 0),
                total_count=total,
            ),
            active_run=active_run,
            failed_run=failed_run,
            progress=progress,
        )

    return SongWorkflowView(stages=stages)


def _invalidates(stage_key: StageKey) -> tuple[StageKey, ...]:
    if stage_key == "transcription":
        return ("world_brief", "storyboard", "image_prompts", "keyframes", "final_video")
    if stage_key == "world_brief":
        return ("storyboard", "image_prompts", "keyframes", "final_video")
    if stage_key == "storyboard":
        return ("image_prompts", "keyframes", "final_video")
    if stage_key == "image_prompts":
        return ("keyframes", "final_video")
    if stage_key == "keyframes":
        return ("final_video",)
    return ()
