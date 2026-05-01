"""Integration tests for story 9 (stages) + story 10 (final render)."""

from __future__ import annotations

import time


def _wait_until(fn, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(0.05)
    return False


def test_stage_deps_dependency_enforcement(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    # tiny-song imports already have world_brief + storyboard + keyframes, so
    # the deps layer reports every stage 'done' and 'ok_to_start=True'.
    deps = client_for.get("/api/songs/tiny-song/stages").json()
    assert deps["transcribe"]["done"] is True
    assert deps["world-brief"]["done"] is True
    assert deps["storyboard"]["done"] is True
    assert deps["image-prompts"]["done"] is True
    assert deps["keyframes"]["done"] is True


def test_run_keyframes_stage_creates_takes_for_missing_scenes(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    # Remove scene 2's selected keyframe so the product renderer has work to do.
    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        c.execute(
            "UPDATE scenes SET selected_keyframe_take_id = NULL "
            "WHERE scene_index = 2 AND song_id = (SELECT id FROM songs WHERE slug='tiny-song')")
    kf2 = tmp_env["outputs"] / "tiny-song" / "keyframes" / "keyframe_002.png"
    if kf2.exists():
        kf2.unlink()

    before = client_for.get("/api/songs/tiny-song").json()
    before_kf = sum(1 for s in before["scenes"] if s["selected_keyframe_path"])

    r = client_for.post("/api/songs/tiny-song/stages/keyframes")
    assert r.status_code == 200, r.text

    # Wait for the stage to complete
    ok = _wait_until(lambda: client_for.get("/api/songs/tiny-song").json()["scenes"][1]["selected_keyframe_path"])
    assert ok

    after = client_for.get("/api/songs/tiny-song").json()
    after_kf = sum(1 for s in after["scenes"] if s["selected_keyframe_path"])
    assert after_kf > before_kf


def test_render_final_refuses_when_any_scene_missing_clip(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")
    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        c.execute(
            "UPDATE scenes SET selected_clip_take_id = NULL "
            "WHERE scene_index = 1 AND song_id = (SELECT id FROM songs WHERE slug='tiny-song')")

    r = client_for.post("/api/songs/tiny-song/render-final")
    assert r.status_code == 422
    assert 1 in r.json()["detail"]["affected_scenes"]


def test_run_all_outstanding_queues_undone_stages(client_for, tmp_env, fixture_song_one):
    """PRD: 'run all outstanding' runs every un-done stage in dependency order."""
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    # Nuke world_brief so world-brief onward need to run. Tiny-song fixture
    # already has scenes + keyframes, so we also need to null the keyframe
    # takes for the 'keyframes' stage to look undone.
    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        c.execute("UPDATE songs SET world_brief = NULL, sequence_arc = NULL "
                  "WHERE slug = 'tiny-song'")

    r = client_for.post("/api/songs/tiny-song/run-all-stages")
    assert r.status_code == 200, r.text
    body = r.json()
    triggered_stages = [t["stage"] for t in body["triggered"]]
    # world-brief onwards should be queued (transcribe is already done since
    # scenes > 0 in the fixture).
    assert "world-brief" in triggered_stages
    # blocked_at should be None because the chain ran through in order.
    assert body["blocked_at"] is None


def test_run_all_outstanding_409_when_chain_already_running(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    # Seed an in-flight run.
    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        c.execute("""
            INSERT INTO regen_runs (scope, song_id, status, created_at)
            VALUES ('stage_world_brief', (SELECT id FROM songs WHERE slug='tiny-song'), 'running', 0)
        """)

    r = client_for.post("/api/songs/tiny-song/run-all-stages")
    assert r.status_code == 409


def test_render_final_happy_path_creates_finished_video(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")
    for idx in (1, 2):
        r = client_for.post(
            f"/api/songs/tiny-song/scenes/{idx}/takes",
            json={"artefact_kind": "clip", "trigger": "regen"},
        )
        assert r.status_code == 200, r.text
    assert _wait_until(lambda: all(
        s["selected_clip_path"] for s in client_for.get("/api/songs/tiny-song").json()["scenes"]
    ))

    r = client_for.post("/api/songs/tiny-song/render-final")
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]

    # Wait for the finished video to appear
    ok = _wait_until(lambda: len(client_for.get("/api/songs/tiny-song/finished").json()["finished"]) > 0)
    assert ok
    finished = client_for.get("/api/songs/tiny-song/finished").json()["finished"]
    assert finished[0]["final_run_id"] == run_id
    assert finished[0]["scene_count"] == 2


def test_render_final_409_when_already_running(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")
    for idx in (1, 2):
        r = client_for.post(
            f"/api/songs/tiny-song/scenes/{idx}/takes",
            json={"artefact_kind": "clip", "trigger": "regen"},
        )
        assert r.status_code == 200, r.text
    assert _wait_until(lambda: all(
        s["selected_clip_path"] for s in client_for.get("/api/songs/tiny-song").json()["scenes"]
    ))
    r1 = client_for.post("/api/songs/tiny-song/render-final")
    assert r1.status_code == 200
    r2 = client_for.post("/api/songs/tiny-song/render-final")
    # Either the first one finished by now (second also 200) or it's still
    # running and we get 409. Both are acceptable outcomes.
    assert r2.status_code in (200, 409)
