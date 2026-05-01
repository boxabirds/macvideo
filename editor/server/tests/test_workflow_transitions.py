"""Story 33 workflow transition authority tests."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from editor.server.store.schema import init_db
from editor.server.workflow import (
    STAGE_DEFS,
    TRANSITION_MATRIX,
    WorkflowActionRequest,
    assert_transition_matrix_complete,
    plan_workflow_transition,
)
from editor.server.workflow.state import ActionState
from editor.server.workflow.transitions import STAGE_KEY_TO_SCOPE, WorkflowActionKind


ACTIONS: tuple[WorkflowActionKind, ...] = ("start", "retry", "regenerate", "configure")


def _db(tmp_path: Path):
    dbp = tmp_path / "workflow-transitions.db"
    init_db(dbp)
    conn = sqlite3.connect(str(dbp), isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _song(conn, *, filter_="charcoal", abstraction=0, world=None, storyboard=None, duration=120):
    now = time.time()
    conn.execute(
        """
        INSERT INTO songs (
            slug, audio_path, duration_s, size_bytes, filter, abstraction,
            quality_mode, world_brief, sequence_arc, created_at, updated_at
        ) VALUES ('song', '/song.wav', ?, 100, ?, ?, 'draft', ?, ?, ?, ?)
        """,
        (duration, filter_, abstraction, world, storyboard, now, now),
    )
    return conn.execute("SELECT id FROM songs WHERE slug = 'song'").fetchone()["id"]


def _scene(conn, song_id, idx=1, *, beat="beat", prompt=None, keyframe=False, clip=False, dirty="[]"):
    now = time.time()
    cur = conn.execute(
        """
        INSERT INTO scenes (
            song_id, scene_index, kind, target_text, start_s, end_s,
            target_duration_s, num_frames, beat, image_prompt, dirty_flags,
            created_at, updated_at
        ) VALUES (?, ?, 'lyric', 'line', 0, 1, 1, 24, ?, ?, ?, ?, ?)
        """,
        (song_id, idx, beat, prompt, dirty, now, now),
    )
    scene_id = cur.lastrowid
    if keyframe:
        take = conn.execute(
            "INSERT INTO takes (scene_id, artefact_kind, asset_path, created_by, created_at) "
            "VALUES (?, 'keyframe', '/tmp/keyframe.png', 'editor', ?)",
            (scene_id, now),
        )
        conn.execute("UPDATE scenes SET selected_keyframe_take_id = ? WHERE id = ?", (take.lastrowid, scene_id))
    if clip:
        take = conn.execute(
            "INSERT INTO takes (scene_id, artefact_kind, asset_path, created_by, created_at) "
            "VALUES (?, 'clip', '/tmp/clip.mp4', 'editor', ?)",
            (scene_id, now),
        )
        conn.execute("UPDATE scenes SET selected_clip_take_id = ? WHERE id = ?", (take.lastrowid, scene_id))


def _run(conn, song_id, *, scope="stage_world_brief", status="failed", error="boom"):
    conn.execute(
        """
        INSERT INTO regen_runs (
            scope, song_id, status, error, started_at, ended_at, created_at
        ) VALUES (?, ?, ?, ?, 1, 2, ?)
        """,
        (scope, song_id, status, error, time.time()),
    )


def test_transition_matrix_is_complete_and_mece():
    assert_transition_matrix_complete()
    assert set(TRANSITION_MATRIX) == set(ActionState.__args__)  # type: ignore[attr-defined]
    for state, by_action in TRANSITION_MATRIX.items():
        assert set(by_action) == set(ACTIONS), state
        assert all(outcome.startswith(("accept_", "reject_")) for outcome in by_action.values())


def test_every_canonical_stage_has_transition_scope():
    assert {stage.key for stage in STAGE_DEFS} == set(STAGE_KEY_TO_SCOPE)


@pytest.mark.parametrize(
    ("state_name", "requested_action", "expected_outcome"),
    [
        ("blocked", "start", "reject_blocked"),
        ("blocked", "retry", "reject_blocked"),
        ("blocked", "regenerate", "reject_blocked"),
        ("available", "start", "accept_start"),
        ("available", "retry", "reject_invalid_action"),
        ("available", "regenerate", "reject_invalid_action"),
        ("done", "start", "accept_regenerate"),
        ("done", "retry", "reject_invalid_action"),
        ("done", "regenerate", "accept_regenerate"),
        ("retryable", "start", "reject_invalid_action"),
        ("retryable", "retry", "accept_retry"),
        ("retryable", "regenerate", "reject_invalid_action"),
        ("running", "start", "reject_conflict"),
        ("running", "retry", "reject_conflict"),
        ("running", "regenerate", "reject_conflict"),
        ("stale", "start", "accept_regenerate"),
        ("stale", "retry", "reject_invalid_action"),
        ("stale", "regenerate", "accept_regenerate"),
    ],
)
def test_transition_authority_applies_mece_outcomes(tmp_path, state_name, requested_action, expected_outcome):
    conn = _db(tmp_path)
    song_id, stage = _song_in_state(conn, state_name)

    result = plan_workflow_transition(
        conn,
        song_id=song_id,
        request=WorkflowActionRequest(stage=stage, action=requested_action),
    )

    assert result.outcome == expected_outcome
    assert result.accepted is expected_outcome.startswith("accept_")


def test_active_workflow_run_blocks_other_workflow_actions(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, world="world", storyboard="arc")
    _scene(conn, song_id, prompt="prompt", keyframe=True)
    _run(conn, song_id, scope="stage_world_brief", status="running", error=None)

    result = plan_workflow_transition(
        conn,
        song_id=song_id,
        request=WorkflowActionRequest(stage="keyframes", action="start"),
    )

    assert result.accepted is False
    assert result.outcome == "reject_conflict"
    assert result.reason_code == "workflow_busy"


def test_visual_language_configuration_is_a_world_transition(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, filter_=None, abstraction=None)
    _scene(conn, song_id)

    result = plan_workflow_transition(
        conn,
        song_id=song_id,
        request=WorkflowActionRequest(stage="world_brief", action="configure", run_scope="song_filter"),
    )

    assert result.accepted is True
    assert result.outcome == "accept_start"
    assert result.scope == "song_filter"


def test_visual_language_configuration_requires_transcription(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, filter_=None, abstraction=None, world="world")

    result = plan_workflow_transition(
        conn,
        song_id=song_id,
        request=WorkflowActionRequest(stage="world_brief", action="configure"),
    )

    assert result.accepted is False
    assert result.outcome == "reject_blocked"
    assert result.message == "Complete transcription first."


def test_visual_language_configuration_on_existing_world_invalidates_downstream(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, world="world")
    _scene(conn, song_id)

    result = plan_workflow_transition(
        conn,
        song_id=song_id,
        request=WorkflowActionRequest(stage="world_brief", action="configure", run_scope="song_filter"),
    )

    assert result.accepted is True
    assert result.outcome == "accept_regenerate"
    assert result.invalidates == ("storyboard", "image_prompts", "keyframes", "final_video")


def test_visual_language_configuration_is_not_a_separate_downstream_transition(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, world="world", storyboard="arc")
    _scene(conn, song_id, prompt="prompt")

    result = plan_workflow_transition(
        conn,
        song_id=song_id,
        request=WorkflowActionRequest(stage="keyframes", action="configure"),
    )

    assert result.accepted is False
    assert result.reason_code == "invalid_action"


def _song_in_state(conn, state_name: str):
    if state_name == "blocked":
        return _song(conn), "world_brief"
    if state_name == "available":
        song_id = _song(conn)
        _scene(conn, song_id)
        return song_id, "world_brief"
    if state_name == "done":
        song_id = _song(conn, world="world")
        _scene(conn, song_id)
        return song_id, "world_brief"
    if state_name == "retryable":
        song_id = _song(conn)
        _scene(conn, song_id)
        _run(conn, song_id, status="failed")
        return song_id, "world_brief"
    if state_name == "running":
        song_id = _song(conn)
        _scene(conn, song_id)
        _run(conn, song_id, status="running", error=None)
        return song_id, "world_brief"
    if state_name == "stale":
        song_id = _song(conn, world="world", storyboard="arc")
        _scene(conn, song_id, prompt="prompt", keyframe=True, dirty='["keyframe_stale"]')
        return song_id, "keyframes"
    raise AssertionError(f"unknown state fixture {state_name}")
