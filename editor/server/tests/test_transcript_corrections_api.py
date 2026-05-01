"""Story 15 — timestamp-preserving transcript corrections."""

from __future__ import annotations


def _setup(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")


def test_get_transcript_seeds_words_from_scene_timing(client_for, tmp_env, fixture_song_one):
    _setup(client_for, tmp_env, fixture_song_one)
    r = client_for.get("/api/songs/tiny-song/scenes/1/transcript")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [w["text"] for w in body["words"]] == ["la", "la", "la"]
    assert body["words"][0]["start_s"] == 0.0
    assert body["words"][-1]["end_s"] == 0.3


def test_correction_preserves_untouched_word_timestamps(client_for, tmp_env, fixture_song_one):
    _setup(client_for, tmp_env, fixture_song_one)
    before = client_for.get("/api/songs/tiny-song/scenes/1/transcript").json()["words"]

    r = client_for.post(
        "/api/songs/tiny-song/scenes/1/transcript/corrections",
        json={"start_word_index": 1, "end_word_index": 1, "text": "gravid bag"},
    )
    assert r.status_code == 200, r.text
    words = r.json()["words"]
    assert [w["text"] for w in words] == ["la", "gravid", "bag", "la"]
    assert words[0]["start_s"] == before[0]["start_s"]
    assert words[0]["end_s"] == before[0]["end_s"]
    assert words[-1]["start_s"] == before[2]["start_s"]
    assert words[-1]["end_s"] == before[2]["end_s"]
    assert words[1]["start_s"] == before[1]["start_s"]
    assert words[2]["end_s"] == before[1]["end_s"]

    scene = client_for.get("/api/songs/tiny-song/scenes/1").json()
    assert scene["target_text"] == "la gravid bag la"


def test_empty_correction_is_rejected_to_preserve_timing_anchors(client_for, tmp_env, fixture_song_one):
    _setup(client_for, tmp_env, fixture_song_one)
    r = client_for.post(
        "/api/songs/tiny-song/scenes/1/transcript/corrections",
        json={"start_word_index": 1, "end_word_index": 1, "text": ""},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "empty_correction"


def test_correction_marks_downstream_outputs_stale(client_for, tmp_env, fixture_song_one):
    _setup(client_for, tmp_env, fixture_song_one)
    r = client_for.post(
        "/api/songs/tiny-song/scenes/1/transcript/corrections",
        json={"start_word_index": 0, "end_word_index": 0, "text": "gravid"},
    )
    assert r.status_code == 200, r.text
    scene1 = client_for.get("/api/songs/tiny-song/scenes/1").json()
    scene2 = client_for.get("/api/songs/tiny-song/scenes/2").json()
    assert "keyframe_stale" in scene1["dirty_flags"]
    assert "clip_stale" in scene1["dirty_flags"]
    assert "keyframe_stale" in scene2["dirty_flags"]


def test_undo_and_redo_survive_reload_path(client_for, tmp_env, fixture_song_one):
    _setup(client_for, tmp_env, fixture_song_one)
    client_for.post(
        "/api/songs/tiny-song/scenes/1/transcript/corrections",
        json={"start_word_index": 0, "end_word_index": 0, "text": "gravid"},
    )
    assert client_for.get("/api/songs/tiny-song/scenes/1").json()["target_text"] == "gravid la la"

    undo = client_for.post("/api/songs/tiny-song/transcript/undo")
    assert undo.status_code == 200, undo.text
    assert undo.json()["target_text"] == "la la la"

    redo = client_for.post("/api/songs/tiny-song/transcript/redo")
    assert redo.status_code == 200, redo.text
    assert redo.json()["target_text"] == "gravid la la"


def test_revert_correction_restores_original_words(client_for, tmp_env, fixture_song_one):
    _setup(client_for, tmp_env, fixture_song_one)
    corrected = client_for.post(
        "/api/songs/tiny-song/scenes/1/transcript/corrections",
        json={"start_word_index": 0, "end_word_index": 1, "text": "gravid"},
    ).json()
    correction_id = next(w["correction_id"] for w in corrected["words"] if w["correction_id"])

    r = client_for.post(f"/api/songs/tiny-song/scenes/1/transcript/corrections/{correction_id}/revert")
    assert r.status_code == 200, r.text
    assert r.json()["target_text"] == "la la la"


def test_undo_preserves_other_applied_corrections(client_for, tmp_env, fixture_song_one):
    _setup(client_for, tmp_env, fixture_song_one)
    first = client_for.post(
        "/api/songs/tiny-song/scenes/1/transcript/corrections",
        json={"start_word_index": 0, "end_word_index": 0, "text": "gravid"},
    ).json()
    first_id = next(w["correction_id"] for w in first["words"] if w["text"] == "gravid")
    second = client_for.post(
        "/api/songs/tiny-song/scenes/1/transcript/corrections",
        json={"start_word_index": 2, "end_word_index": 2, "text": "bag"},
    )
    assert second.status_code == 200, second.text

    undo = client_for.post("/api/songs/tiny-song/transcript/undo")
    assert undo.status_code == 200, undo.text
    words = undo.json()["words"]
    assert [w["text"] for w in words] == ["gravid", "la", "la"]
    assert words[0]["correction_id"] == first_id
    assert words[1]["correction_id"] is None
    assert words[2]["correction_id"] is None


def test_invalid_selection_has_error_code(client_for, tmp_env, fixture_song_one):
    _setup(client_for, tmp_env, fixture_song_one)
    r = client_for.post(
        "/api/songs/tiny-song/scenes/1/transcript/corrections",
        json={"start_word_index": 3, "end_word_index": 9, "text": "nope"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_word_selection"
