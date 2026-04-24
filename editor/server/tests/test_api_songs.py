"""Integration tests for the songs / scenes HTTP routes."""

from __future__ import annotations

import json


def test_list_songs_empty(client_for):
    r = client_for.get("/api/songs")
    assert r.status_code == 200
    assert r.json() == {"songs": []}


def test_list_songs_after_import(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    # Trigger import via the endpoint
    r = client_for.post("/api/import")
    assert r.status_code == 200
    report = r.json()
    assert report["totals"]["songs"] == 1
    assert report["totals"]["scenes"] == 2

    r = client_for.get("/api/songs")
    data = r.json()
    assert len(data["songs"]) == 1
    s = data["songs"][0]
    assert s["slug"] == "tiny-song"
    assert s["status"]["transcription"] == "done"
    assert s["status"]["keyframes_done"] == 2
    assert s["status"]["keyframes_total"] == 2
    assert s["status"]["clips_done"] == 0


def test_get_song_detail_and_scene(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    r = client_for.get("/api/songs/tiny-song")
    detail = r.json()
    assert len(detail["scenes"]) == 2
    assert detail["scenes"][0]["beat"] == "beat one"
    # Rehydrated from .24fps.bak
    assert detail["scenes"][0]["next_link"] == "Leading into beat two"

    r = client_for.get("/api/songs/tiny-song/scenes/1")
    scene = r.json()
    assert scene["camera_intent"] == "static hold"


def test_patch_scene_beat_marks_stale(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    r = client_for.patch("/api/songs/tiny-song/scenes/1",
                         json={"beat": "new beat"})
    assert r.status_code == 200
    scene = r.json()
    assert "keyframe_stale" in scene["dirty_flags"]
    assert "clip_stale" in scene["dirty_flags"]

    # Identity-chain neighbour should be keyframe_stale but not clip_stale
    r = client_for.get("/api/songs/tiny-song/scenes/2")
    assert r.json()["dirty_flags"] == ["keyframe_stale"]


def test_patch_scene_invalid_camera_intent(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    r = client_for.patch("/api/songs/tiny-song/scenes/1",
                         json={"camera_intent": "backflip"})
    assert r.status_code == 422


def test_patch_song_filter_and_quality_mode(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    r = client_for.patch("/api/songs/tiny-song",
                         json={"filter": "stained glass", "quality_mode": "final"})
    assert r.status_code == 200
    detail = r.json()
    assert detail["filter"] == "stained glass"
    assert detail["quality_mode"] == "final"


def test_get_unknown_scene_returns_404(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    r = client_for.get("/api/songs/tiny-song/scenes/999")
    assert r.status_code == 404


def test_missing_asset_surfaced_on_scene_get(client_for, tmp_env, fixture_song_one):
    """Delete the keyframe file after import. GET must return the scene with
    `missing_assets=['keyframe']`, not silently hide it."""
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    (tmp_env["outputs"] / "tiny-song" / "keyframes" / "keyframe_001.png").unlink()

    r = client_for.get("/api/songs/tiny-song/scenes/1")
    assert r.status_code == 200
    scene = r.json()
    assert scene["missing_assets"] == ["keyframe"]


def test_range_request_on_wav_returns_206(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    # File is small (0.5s of PCM), but a range of bytes 10-50 is still valid
    r = client_for.get("/assets/music/tiny-song.wav",
                       headers={"Range": "bytes=10-50"})
    assert r.status_code == 206
    assert r.headers["content-range"].startswith("bytes 10-50/")
    assert r.headers["accept-ranges"] == "bytes"


def test_camera_intents_endpoint(client_for):
    r = client_for.get("/api/camera-intents")
    assert r.status_code == 200
    vals = r.json()["values"]
    assert "static hold" in vals
    assert len(vals) == 11


def test_import_endpoint_idempotent(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    r1 = client_for.post("/api/import").json()
    r2 = client_for.post("/api/import").json()
    assert r1["totals"]["scenes"] == 2
    assert r2["totals"]["scenes"] == 0   # no new scenes on second pass
