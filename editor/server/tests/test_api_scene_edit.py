"""Integration tests for story 3 — per-scene PATCH.

Covers edit.field-save (backend contract), edit.staleness-cascade (dirty
flag propagation including the identity-chain neighbours), and
edit.user-authored-prompt (flag flip on image_prompt edit).

These pin the exact wire contract the frontend Storyboard component depends
on. Breaks here mean the editor silently does the wrong thing.
"""

from __future__ import annotations


def test_patch_beat_marks_downstream_stale(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    r = client_for.patch(
        "/api/songs/tiny-song/scenes/1",
        json={"beat": "rewritten beat for scene 1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["beat"] == "rewritten beat for scene 1"
    assert "keyframe_stale" in body["dirty_flags"]
    assert "clip_stale" in body["dirty_flags"]


def test_patch_image_prompt_sets_user_authored(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    r = client_for.patch(
        "/api/songs/tiny-song/scenes/1",
        json={"image_prompt": "a hand-written prompt"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["image_prompt"] == "a hand-written prompt"
    assert body["prompt_is_user_authored"] is True


def test_patch_camera_intent_rejects_unknown_value(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    r = client_for.patch(
        "/api/songs/tiny-song/scenes/1",
        json={"camera_intent": "make stuff up"},
    )
    # FastAPI validation failure on the custom validator is 422.
    assert r.status_code == 422
    # Scene is untouched.
    current = client_for.get("/api/songs/tiny-song/scenes/1").json()
    assert current["camera_intent"] != "make stuff up"


def test_patch_unchanged_value_is_noop_on_flags(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    before = client_for.get("/api/songs/tiny-song/scenes/1").json()
    r = client_for.patch(
        "/api/songs/tiny-song/scenes/1",
        json={"beat": before["beat"]},
    )
    assert r.status_code == 200
    after = r.json()
    # Dirty flags shouldn't have moved — no editable field actually changed.
    assert set(after["dirty_flags"]) == set(before["dirty_flags"])


def test_patch_cascades_to_identity_chain_neighbours(client_for, tmp_env, fixture_song_one):
    """Beat/camera/subject edit on scene N cascades keyframe_stale to N+1..N+4.

    The tiny-song fixture only has 2 scenes, so editing scene 1 should
    cascade to scene 2's dirty_flags (keyframe_stale, no clip_stale).
    """
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    # Edit scene 1's beat
    client_for.patch(
        "/api/songs/tiny-song/scenes/1",
        json={"beat": "new beat on scene 1"},
    )

    scene2 = client_for.get("/api/songs/tiny-song/scenes/2").json()
    assert "keyframe_stale" in scene2["dirty_flags"]
    # clip_stale should NOT propagate via the identity chain, only
    # keyframe_stale does (identity chain affects keyframe appearance).
    assert "clip_stale" not in scene2["dirty_flags"]


def test_reset_user_authored_flag_to_false(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    client_for.patch(
        "/api/songs/tiny-song/scenes/1",
        json={"image_prompt": "user edit"},
    )
    # Explicitly reset — next CLI pass can re-author the prompt.
    r = client_for.patch(
        "/api/songs/tiny-song/scenes/1",
        json={"prompt_is_user_authored": False},
    )
    assert r.status_code == 200
    assert r.json()["prompt_is_user_authored"] is False


def test_patch_target_text_persists_phrase_without_overwriting_beat(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    before = client_for.get("/api/songs/tiny-song/scenes/1").json()
    r = client_for.patch(
        "/api/songs/tiny-song/scenes/1",
        json={"target_text": "corrected transcript phrase"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target_text"] == "corrected transcript phrase"
    assert body["beat"] == before["beat"]
    assert "keyframe_stale" in body["dirty_flags"]
    assert "clip_stale" in body["dirty_flags"]

    reloaded = client_for.get("/api/songs/tiny-song/scenes/1").json()
    assert reloaded["target_text"] == "corrected transcript phrase"
    assert reloaded["beat"] == before["beat"]
