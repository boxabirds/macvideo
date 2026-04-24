"""Integration tests for story 4 — filter/abstraction chain.

Covers:
- POST /api/songs/:slug/preview-change (estimate-modal capability)
- PATCH /api/songs/:slug with filter|abstraction triggers the chain
  (chain-execute capability)
- PATCH is 409 while a chain is in flight
- quality-mode changes do NOT trigger the chain

Uses fake_gen_keyframes.py so no Gemini calls fire.
"""

from __future__ import annotations

import time


def _wait_until(fn, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(0.05)
    return False


def test_preview_change_returns_scope_and_estimate(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    r = client_for.post(
        "/api/songs/tiny-song/preview-change",
        json={"filter": "cyanotype"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["from"]["filter"] == "charcoal"
    assert body["to"]["filter"] == "cyanotype"
    assert body["scope"]["will_regen_world_brief"] is True
    assert body["scope"]["will_regen_storyboard"] is True
    assert body["scope"]["keyframes_to_generate"] == 2
    assert body["estimate"]["gemini_calls"] > 0
    assert body["estimate"]["estimated_usd"] >= 0
    assert body["estimate"]["confidence"] in ("high", "medium")
    assert body["would_conflict_with"] is None


def test_preview_change_422_on_both_fields_set(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    r = client_for.post(
        "/api/songs/tiny-song/preview-change",
        json={"filter": "cyanotype", "abstraction": 50},
    )
    assert r.status_code == 422


def test_filter_change_enqueues_chain_and_marks_clips_stale(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    # Seed a clip take on scene 1 so we can verify it's marked stale.
    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        scene = c.execute(
            "SELECT id FROM scenes WHERE scene_index = 1 AND song_id = "
            "(SELECT id FROM songs WHERE slug='tiny-song')"
        ).fetchone()
        cur = c.execute(
            "INSERT INTO takes (scene_id, artefact_kind, asset_path, created_by, created_at) "
            "VALUES (?, 'clip', '/fake/clip_001.mp4', 'cli', 0)",
            (scene["id"],),
        )
        c.execute(
            "UPDATE scenes SET selected_clip_take_id = ? WHERE id = ?",
            (cur.lastrowid, scene["id"]),
        )

    r = client_for.patch(
        "/api/songs/tiny-song",
        json={"filter": "cyanotype"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filter"] == "cyanotype"
    # world_brief cleared on chain trigger
    assert body["world_brief"] is None
    # scene 1's clip is marked stale
    scene1 = next(s for s in body["scenes"] if s["index"] == 1)
    assert "clip_stale" in scene1["dirty_flags"]

    # A song_filter regen run should be active.
    runs = client_for.get("/api/songs/tiny-song/regen").json()["runs"]
    filter_runs = [r for r in runs if r["scope"] == "song_filter"]
    assert len(filter_runs) >= 1


def test_patch_song_409_while_chain_running(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    # Create a fake in-progress run
    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        song = c.execute("SELECT id FROM songs WHERE slug='tiny-song'").fetchone()
        c.execute("""
            INSERT INTO regen_runs (scope, song_id, status, created_at)
            VALUES ('song_filter', ?, 'running', ?)
        """, (song["id"], time.time()))

    r = client_for.patch(
        "/api/songs/tiny-song", json={"filter": "cyanotype"},
    )
    assert r.status_code == 409


def test_quality_mode_change_does_not_trigger_chain(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    r = client_for.patch(
        "/api/songs/tiny-song", json={"quality_mode": "final"},
    )
    assert r.status_code == 200
    assert r.json()["quality_mode"] == "final"

    runs = client_for.get("/api/songs/tiny-song/regen").json()["runs"]
    # No song_filter / song_abstraction runs should be present for this mode change.
    assert not any(r["scope"] in ("song_filter", "song_abstraction") for r in runs)


def test_quality_mode_change_marks_existing_clips_stale(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    # Seed a clip take
    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        scene = c.execute(
            "SELECT id FROM scenes WHERE scene_index = 1 AND song_id = "
            "(SELECT id FROM songs WHERE slug='tiny-song')"
        ).fetchone()
        cur = c.execute(
            "INSERT INTO takes (scene_id, artefact_kind, asset_path, quality_mode, created_by, created_at) "
            "VALUES (?, 'clip', '/fake/clip_draft.mp4', 'draft', 'cli', 0)",
            (scene["id"],),
        )
        c.execute(
            "UPDATE scenes SET selected_clip_take_id = ? WHERE id = ?",
            (cur.lastrowid, scene["id"]),
        )

    r = client_for.patch(
        "/api/songs/tiny-song", json={"quality_mode": "final"},
    )
    assert r.status_code == 200
    scene1 = next(s for s in r.json()["scenes"] if s["index"] == 1)
    assert "clip_stale" in scene1["dirty_flags"]
