"""Command-side workflow transition rules.

The state module describes what the song looks like. This module decides
whether a requested workflow action is allowed before routes mutate state or
queue work.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Mapping, TypeAlias

from .state import ActionState, StageKey, _invalidates, evaluate_song_workflow


WorkflowActionKind: TypeAlias = Literal["start", "retry", "regenerate", "configure"]
TransitionOutcome: TypeAlias = Literal[
    "accept_start",
    "accept_retry",
    "accept_regenerate",
    "accept_noop",
    "reject_blocked",
    "reject_conflict",
    "reject_invalid_action",
]


STAGE_NAME_TO_KEY: Mapping[str, StageKey] = {
    "transcribe": "transcription",
    "world-brief": "world_brief",
    "storyboard": "storyboard",
    "image-prompts": "image_prompts",
    "keyframes": "keyframes",
    "render-final": "final_video",
    "final-video": "final_video",
}

STAGE_KEY_TO_SCOPE: Mapping[StageKey, str] = {
    "transcription": "stage_audio_transcribe",
    "world_brief": "stage_world_brief",
    "storyboard": "stage_storyboard",
    "image_prompts": "stage_image_prompts",
    "keyframes": "stage_keyframes",
    "final_video": "final_video",
}

WORKFLOW_RUN_SCOPES = frozenset({
    "stage_audio_transcribe",
    "stage_world_brief",
    "stage_storyboard",
    "stage_image_prompts",
    "stage_keyframes",
    "song_filter",
    "song_abstraction",
    "final_video",
})

TRANSITION_MATRIX: Mapping[ActionState, Mapping[WorkflowActionKind, TransitionOutcome]] = {
    "blocked": {
        "start": "reject_blocked",
        "retry": "reject_blocked",
        "regenerate": "reject_blocked",
        "configure": "reject_blocked",
    },
    "available": {
        "start": "accept_start",
        "retry": "reject_invalid_action",
        "regenerate": "reject_invalid_action",
        "configure": "reject_invalid_action",
    },
    "done": {
        "start": "accept_regenerate",
        "retry": "reject_invalid_action",
        "regenerate": "accept_regenerate",
        "configure": "reject_invalid_action",
    },
    "stale": {
        "start": "accept_regenerate",
        "retry": "reject_invalid_action",
        "regenerate": "accept_regenerate",
        "configure": "reject_invalid_action",
    },
    "retryable": {
        "start": "reject_invalid_action",
        "retry": "accept_retry",
        "regenerate": "reject_invalid_action",
        "configure": "reject_invalid_action",
    },
    "running": {
        "start": "reject_conflict",
        "retry": "reject_conflict",
        "regenerate": "reject_conflict",
        "configure": "reject_conflict",
    },
}


@dataclass(frozen=True)
class WorkflowActionRequest:
    stage: StageKey
    action: WorkflowActionKind
    run_scope: str | None = None


@dataclass(frozen=True)
class WorkflowTransitionPlan:
    accepted: Literal[True]
    stage: StageKey
    stage_name: str
    scope: str
    action: WorkflowActionKind
    outcome: TransitionOutcome
    invalidates: tuple[StageKey, ...]
    active_run_id: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WorkflowTransitionRejection:
    accepted: Literal[False]
    stage: StageKey
    action: WorkflowActionKind
    outcome: TransitionOutcome
    reason_code: str
    message: str
    active_run_id: int | None = None

    def to_http_detail(self) -> dict[str, object]:
        return {
            "code": "workflow_transition_rejected",
            "stage": self.stage,
            "action": self.action,
            "reason_code": self.reason_code,
            "reason": self.message,
            "active_run_id": self.active_run_id,
        }


WorkflowTransition = WorkflowTransitionPlan | WorkflowTransitionRejection


def stage_key_from_name(stage_name: str) -> StageKey | None:
    return STAGE_NAME_TO_KEY.get(stage_name)


def assert_transition_matrix_complete() -> None:
    missing_states = set(ActionState.__args__) - set(TRANSITION_MATRIX)  # type: ignore[attr-defined]
    extra_states = set(TRANSITION_MATRIX) - set(ActionState.__args__)  # type: ignore[attr-defined]
    if missing_states or extra_states:
        raise AssertionError(f"transition matrix state mismatch: missing={missing_states}, extra={extra_states}")
    expected_actions = {"start", "retry", "regenerate", "configure"}
    for state, actions in TRANSITION_MATRIX.items():
        missing_actions = expected_actions - set(actions)
        extra_actions = set(actions) - expected_actions
        if missing_actions or extra_actions:
            raise AssertionError(
                f"transition matrix action mismatch for {state}: "
                f"missing={missing_actions}, extra={extra_actions}"
            )


def plan_workflow_transition(
    conn,
    *,
    song_id: int,
    request: WorkflowActionRequest,
) -> WorkflowTransition:
    assert_transition_matrix_complete()
    workflow = evaluate_song_workflow(conn, song_id)
    stage = workflow.stages[request.stage]
    active_conflict = _active_workflow_run(conn, song_id)

    if request.action == "configure":
        return _plan_configure_transition(
            workflow=workflow,
            request=request,
            active_conflict=active_conflict,
        )

    if active_conflict is not None and stage.state != "running":
        return WorkflowTransitionRejection(
            accepted=False,
            stage=request.stage,
            action=request.action,
            outcome="reject_conflict",
            reason_code="workflow_busy",
            message=f"another workflow action is already running (run {active_conflict})",
            active_run_id=active_conflict,
        )

    outcome = TRANSITION_MATRIX[stage.state][request.action]
    if outcome.startswith("accept_"):
        return WorkflowTransitionPlan(
            accepted=True,
            stage=request.stage,
            stage_name=stage.stage_name,
            scope=request.run_scope or STAGE_KEY_TO_SCOPE[request.stage],
            action=request.action,
            outcome=outcome,
            invalidates=_invalidates(request.stage),
            active_run_id=stage.active_run.id if stage.active_run else None,
        )

    if outcome == "reject_conflict":
        active_run_id = stage.active_run.id if stage.active_run else active_conflict
        return WorkflowTransitionRejection(
            accepted=False,
            stage=request.stage,
            action=request.action,
            outcome=outcome,
            reason_code="workflow_busy",
            message=f"{stage.label} is already running"
            if active_run_id is None
            else f"{stage.label} is already running (run {active_run_id})",
            active_run_id=active_run_id,
        )

    if outcome == "reject_blocked":
        return WorkflowTransitionRejection(
            accepted=False,
            stage=request.stage,
            action=request.action,
            outcome=outcome,
            reason_code="blocked",
            message=stage.blocked_reason or "This action is not available yet.",
        )

    return WorkflowTransitionRejection(
        accepted=False,
        stage=request.stage,
        action=request.action,
        outcome=outcome,
        reason_code="invalid_action",
        message=_invalid_action_message(stage.state, request.action),
    )


def transition_rejection_status(rejection: WorkflowTransitionRejection) -> int:
    return 409 if rejection.reason_code == "workflow_busy" else 422


def _active_workflow_run(conn, song_id: int) -> int | None:
    row = conn.execute(
        f"""
        SELECT id FROM regen_runs
        WHERE song_id = ?
          AND scope IN ({",".join("?" for _ in WORKFLOW_RUN_SCOPES)})
          AND status IN ('pending', 'running')
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (song_id, *sorted(WORKFLOW_RUN_SCOPES)),
    ).fetchone()
    return row["id"] if row else None


def _plan_configure_transition(
    *,
    workflow,
    request: WorkflowActionRequest,
    active_conflict: int | None,
) -> WorkflowTransition:
    if request.stage != "world_brief":
        return WorkflowTransitionRejection(
            accepted=False,
            stage=request.stage,
            action=request.action,
            outcome="reject_invalid_action",
            reason_code="invalid_action",
            message="Only the world step can configure visual language.",
        )

    world = workflow.stages["world_brief"]
    transcription = workflow.stages["transcription"]
    if active_conflict is not None:
        return WorkflowTransitionRejection(
            accepted=False,
            stage=request.stage,
            action=request.action,
            outcome="reject_conflict",
            reason_code="workflow_busy",
            message=f"another workflow action is already running (run {active_conflict})",
            active_run_id=active_conflict,
        )
    # Fresh setup can save visual language before transcript scenes exist.
    # Starting actual world generation remains blocked by normal stage rules.
    fresh_setup = transcription.state == "available" and world.done is False
    if transcription.state != "done" and not fresh_setup:
        return WorkflowTransitionRejection(
            accepted=False,
            stage=request.stage,
            action=request.action,
            outcome="reject_blocked",
            reason_code="blocked",
            message="Complete transcription first.",
        )

    outcome: TransitionOutcome = "accept_regenerate" if world.state in ("done", "stale") else "accept_start"
    return WorkflowTransitionPlan(
        accepted=True,
        stage=request.stage,
        stage_name=world.stage_name,
        scope=request.run_scope or "song_filter",
        action=request.action,
        outcome=outcome,
        invalidates=_invalidates(request.stage),
        active_run_id=None,
    )


def _invalid_action_message(state: ActionState, action: WorkflowActionKind) -> str:
    if state == "done" and action == "start":
        return "This workflow step is already complete."
    if action == "retry":
        return "This workflow step has not failed, so it cannot be retried."
    if action == "regenerate":
        return "This workflow step has no current output to regenerate."
    return "This workflow action is not valid for the current song state."
