"""Story 29 workflow state at HTTP request boundaries."""

from __future__ import annotations


def test_song_detail_serializes_central_workflow(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    body = client_for.get("/api/songs/tiny-song").json()
    workflow = body["workflow"]["stages"]

    assert workflow["transcription"]["state"] == "done"
    assert workflow["world_brief"]["label"] == "world description"
    assert workflow["keyframes"]["state"] == "done"
    assert workflow["final_video"]["state"] == "available"


def test_stage_request_boundary_uses_workflow_blocked_reason(client_for, tmp_env):
    wav = tmp_env["music"] / "blocked-song.wav"
    wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
    client_for.post("/api/import")

    r = client_for.post("/api/songs/blocked-song/stages/keyframes")

    assert r.status_code == 422
    assert r.json()["detail"]["reason"] == "Please generate the world and storyboard first."


def test_workflow_serializes_retryable_failure_and_progress(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")
    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        song_id = c.execute("SELECT id FROM songs WHERE slug = 'tiny-song'").fetchone()["id"]
        c.execute(
            """
            INSERT INTO regen_runs (
                scope, song_id, status, error, progress_pct, phase,
                started_at, ended_at, created_at
            ) VALUES ('stage_world_brief', ?, 'failed', 'world failed', NULL, NULL, 1, 2, 2)
            """,
            (song_id,),
        )
        c.execute(
            """
            INSERT INTO regen_runs (
                scope, song_id, status, error, progress_pct, phase,
                started_at, ended_at, created_at
            ) VALUES ('stage_audio_transcribe', ?, 'running', NULL, 25, 'transcribing', 3, NULL, 3)
            """,
            (song_id,),
        )

    workflow = client_for.get("/api/songs/tiny-song").json()["workflow"]["stages"]

    assert workflow["world_brief"]["state"] == "retryable"
    assert workflow["world_brief"]["failed_reason"] == "world failed"
    assert workflow["transcription"]["state"] == "running"
    assert workflow["transcription"]["progress"]["operation"] == "Transcribing"
    assert workflow["transcription"]["progress"]["processed_seconds"] is not None
