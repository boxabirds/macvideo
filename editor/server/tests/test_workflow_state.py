"""Story 29 centralized song workflow state tests."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from editor.server.store.schema import init_db
from editor.server.workflow import describe_stage_progress, evaluate_song_workflow
from editor.server.workflow.state import RunRef


@pytest.fixture(autouse=True)
def _workflow_providers(monkeypatch):
    monkeypatch.setenv("EDITOR_GENERATION_PROVIDER", "fake")
    monkeypatch.setenv("EDITOR_RENDER_PROVIDER", "fake")


def _db(tmp_path: Path):
    dbp = tmp_path / "workflow.db"
    init_db(dbp)
    conn = sqlite3.connect(str(dbp), isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _song(conn, *, slug="song", filter_="charcoal", abstraction=0, world=None, storyboard=None, duration=120):
    now = time.time()
    conn.execute(
        """
        INSERT INTO songs (
            slug, audio_path, duration_s, size_bytes, filter, abstraction,
            quality_mode, world_brief, sequence_arc, created_at, updated_at
        ) VALUES (?, '/song.wav', ?, 100, ?, ?, 'draft', ?, ?, ?, ?)
        """,
        (slug, duration, filter_, abstraction, world, storyboard, now, now),
    )
    return conn.execute("SELECT id FROM songs WHERE slug = ?", (slug,)).fetchone()["id"]


def _scene(conn, song_id, idx, *, beat=None, prompt=None, keyframe=False, clip=False, dirty=None):
    now = time.time()
    cur = conn.execute(
        """
        INSERT INTO scenes (
            song_id, scene_index, kind, target_text, start_s, end_s,
            target_duration_s, num_frames, beat, image_prompt, dirty_flags,
            created_at, updated_at
        ) VALUES (?, ?, 'lyric', 'line', ?, ?, 1, 24, ?, ?, ?, ?, ?)
        """,
        (song_id, idx, idx - 1, idx, beat, prompt, dirty or "[]", now, now),
    )
    scene_id = cur.lastrowid
    if keyframe:
        take = conn.execute(
            "INSERT INTO takes (scene_id, artefact_kind, asset_path, created_by, created_at) "
            "VALUES (?, 'keyframe', ?, 'editor', ?)",
            (scene_id, f"/tmp/keyframe-{idx}.png", now),
        )
        conn.execute("UPDATE scenes SET selected_keyframe_take_id = ? WHERE id = ?", (take.lastrowid, scene_id))
    if clip:
        take = conn.execute(
            "INSERT INTO takes (scene_id, artefact_kind, asset_path, created_by, created_at) "
            "VALUES (?, 'clip', ?, 'editor', ?)",
            (scene_id, f"/tmp/clip-{idx}.mp4", now),
        )
        conn.execute("UPDATE scenes SET selected_clip_take_id = ? WHERE id = ?", (take.lastrowid, scene_id))


def _run(conn, song_id, *, scope="stage_world_brief", status="failed", error="boom", created=1, phase=None, progress=None):
    conn.execute(
        """
        INSERT INTO regen_runs (
            scope, song_id, status, error, phase, progress_pct,
            started_at, ended_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 1, 2, ?)
        """,
        (scope, song_id, status, error, phase, progress, created),
    )


def test_fresh_song_exposes_first_available_action_and_blocks_later_work(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, filter_=None, abstraction=None)

    workflow = evaluate_song_workflow(conn, song_id).stages

    assert workflow["transcription"].state == "available"
    assert workflow["world_brief"].state == "blocked"
    assert workflow["world_brief"].blocked_reason == "Complete transcription first."
    assert workflow["keyframes"].blocked_reason == "Please generate the world and storyboard first."


def test_transcript_only_song_makes_world_available_and_storyboard_blocked(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, world=None, storyboard=None)
    _scene(conn, song_id, 1)

    workflow = evaluate_song_workflow(conn, song_id).stages

    assert workflow["transcription"].state == "done"
    assert workflow["world_brief"].state == "available"
    assert workflow["storyboard"].state == "blocked"
    assert workflow["storyboard"].blocked_reason == "Complete world description first."


def test_transcript_only_song_without_visual_setup_blocks_world_on_setup(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, filter_=None, abstraction=None, world=None, storyboard=None)
    _scene(conn, song_id, 1)

    workflow = evaluate_song_workflow(conn, song_id).stages

    assert workflow["world_brief"].state == "blocked"
    assert workflow["world_brief"].blocked_reason == "Choose a filter and abstraction first."


def test_configured_world_blocks_on_missing_generation_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("EDITOR_GENERATION_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    conn = _db(tmp_path)
    song_id = _song(conn, filter_="charcoal", abstraction=0, world=None, storyboard=None)
    _scene(conn, song_id, 1)

    workflow = evaluate_song_workflow(conn, song_id).stages

    assert workflow["world_brief"].state == "blocked"
    assert "generation provider" in workflow["world_brief"].blocked_reason


def test_complete_clips_block_final_video_on_missing_render_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("EDITOR_RENDER_PROVIDER", raising=False)
    conn = _db(tmp_path)
    song_id = _song(conn, world="world", storyboard="arc")
    _scene(conn, song_id, 1, beat="b", prompt="p", keyframe=True, clip=True)

    workflow = evaluate_song_workflow(conn, song_id).stages

    assert workflow["final_video"].state == "blocked"
    assert "render adapter" in workflow["final_video"].blocked_reason


def test_complete_keyframes_block_final_video_until_clips_exist(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, world="world", storyboard="arc")
    _scene(conn, song_id, 1, beat="b", prompt="p", keyframe=True)

    workflow = evaluate_song_workflow(conn, song_id).stages

    assert workflow["image_prompts"].state == "done"
    assert workflow["keyframes"].state == "done"
    assert workflow["final_video"].state == "blocked"
    assert workflow["final_video"].blocked_reason == "Render clips for every scene first."


def test_complete_clips_make_final_video_available_until_finished(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, world="world", storyboard="arc")
    _scene(conn, song_id, 1, beat="b", prompt="p", keyframe=True, clip=True)

    workflow = evaluate_song_workflow(conn, song_id).stages

    assert workflow["final_video"].state == "available"


def test_failed_run_is_retryable_and_active_run_wins_after_restart(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)
    _scene(conn, song_id, 1)
    _run(conn, song_id, status="failed", error="model failed", created=1)

    failed = evaluate_song_workflow(conn, song_id).stages["world_brief"]
    assert failed.state == "retryable"
    assert failed.can_retry is True
    assert failed.failed_reason == "model failed"

    _run(conn, song_id, status="running", error=None, created=2)
    running = evaluate_song_workflow(conn, song_id).stages["world_brief"]
    assert running.state == "running"
    assert running.active_run is not None
    assert running.active_run.status == "running"


def test_stale_scene_flags_mark_downstream_actions_without_marking_outputs_current(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, world="world", storyboard="arc")
    _scene(
        conn, song_id, 1, beat="b", prompt="p", keyframe=True, clip=True,
        dirty='["keyframe_stale", "clip_stale"]',
    )

    workflow = evaluate_song_workflow(conn, song_id).stages

    assert workflow["keyframes"].state == "stale"
    assert workflow["keyframes"].done is False
    assert workflow["final_video"].state == "stale"
    assert workflow["final_video"].stale_reasons


def test_operation_progress_covers_audio_time_and_unknown_stage():
    run = RunRef(
        id=1, scope="stage_audio_transcribe", status="running", error=None,
        progress_pct=50, phase="transcribing", started_at=1, ended_at=None,
        created_at=1,
    )

    progress = describe_stage_progress("transcription", run, duration_s=228)

    assert progress is not None
    assert progress.operation == "Transcribing"
    assert progress.processed_seconds == 114
    assert progress.total_seconds == 228

    unknown = describe_stage_progress("future-stage", run, duration_s=None)
    assert unknown is not None
    assert unknown.operation == "Running"


def test_completed_run_has_no_progress_view():
    run = RunRef(
        id=1, scope="stage_keyframes", status="done", error=None,
        progress_pct=100, phase=None, started_at=1, ended_at=2, created_at=1,
    )

    assert describe_stage_progress("keyframes", run) is None
