"""Story 30 product-owned generation service integration tests."""

from __future__ import annotations

import shutil
import time


def _wait_until(fn, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(0.05)
    return False


def _prepare_generation_song(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")
    shutil.rmtree(tmp_env["outputs"] / "tiny-song")
    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        c.execute(
            """
            UPDATE songs
            SET world_brief = NULL, sequence_arc = NULL
            WHERE slug = 'tiny-song'
            """
        )
        c.execute(
            """
            UPDATE scenes
            SET beat = NULL, camera_intent = NULL, subject_focus = NULL,
                prev_link = NULL, next_link = NULL, image_prompt = NULL
            WHERE song_id = (SELECT id FROM songs WHERE slug = 'tiny-song')
            """
        )


def test_world_storyboard_and_prompts_generate_without_historical_files(
    client_for, tmp_env, fixture_song_one, monkeypatch,
):
    _prepare_generation_song(client_for, tmp_env, fixture_song_one)
    monkeypatch.setenv("EDITOR_FAKE_GEN_KEYFRAMES", str(tmp_env["root"] / "missing-legacy.py"))
    monkeypatch.setenv("EDITOR_GENERATION_PROVIDER", "fake")

    r = client_for.post("/api/songs/tiny-song/stages/world-brief")
    assert r.status_code == 200, r.text
    assert _wait_until(lambda: client_for.get("/api/songs/tiny-song").json()["world_brief"])

    r = client_for.post("/api/songs/tiny-song/stages/storyboard")
    assert r.status_code == 200, r.text
    assert _wait_until(lambda: (
        (body := client_for.get("/api/songs/tiny-song").json())["sequence_arc"]
        and all(scene["beat"] for scene in body["scenes"])
    ))

    r = client_for.post("/api/songs/tiny-song/stages/image-prompts")
    assert r.status_code == 200, r.text
    assert _wait_until(lambda: all(
        scene["image_prompt"] for scene in client_for.get("/api/songs/tiny-song").json()["scenes"]
    ))

    body = client_for.get("/api/songs/tiny-song").json()
    assert "Product world for tiny-song" in body["world_brief"]
    assert "Product storyboard arc for tiny-song" in body["sequence_arc"]
    assert all("charcoal frame for scene" in s["image_prompt"] for s in body["scenes"])
    assert "gen_keyframes.py" not in str(body)
    assert "shots.json" not in str(body)

    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        rows = c.execute(
            "SELECT stage, provider, prompt_version FROM generation_provenance ORDER BY id",
        ).fetchall()
    assert [r["stage"] for r in rows] == ["world-brief", "storyboard", "image-prompts"]
    assert {r["provider"] for r in rows} == {"fake"}
    assert all(r["prompt_version"].startswith("product-") for r in rows)


def test_missing_generation_provider_blocks_before_run(
    client_for, tmp_env, fixture_song_one, monkeypatch,
):
    _prepare_generation_song(client_for, tmp_env, fixture_song_one)
    monkeypatch.delenv("EDITOR_GENERATION_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    r = client_for.post("/api/songs/tiny-song/stages/world-brief")

    assert r.status_code == 422
    body = r.json()["detail"]
    assert body["code"] == "workflow_transition_rejected"
    assert body["reason_code"] == "blocked"
    assert "generation provider" in body["reason"]
    assert "gen_keyframes.py" not in str(body)


def test_malformed_provider_failure_is_user_facing_and_preserves_saved_content(
    client_for, tmp_env, fixture_song_one, monkeypatch,
):
    _prepare_generation_song(client_for, tmp_env, fixture_song_one)
    monkeypatch.setenv("EDITOR_GENERATION_PROVIDER", "malformed")

    r = client_for.post("/api/songs/tiny-song/stages/world-brief")
    assert r.status_code == 200, r.text

    def failed():
        from editor.server.store import connection
        with connection(tmp_env["db"]) as c:
            row = c.execute(
                "SELECT status, error FROM regen_runs ORDER BY id DESC LIMIT 1",
            ).fetchone()
            return row and row["status"] == "failed" and "world description" in row["error"]

    assert _wait_until(failed)
    body = client_for.get("/api/songs/tiny-song").json()
    assert body["world_brief"] is None
