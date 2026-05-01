"""Story 27 saved scene records are authoritative at runtime."""

from __future__ import annotations

import json
import time


def _wait_until(fn, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(0.05)
    return False


def test_song_detail_uses_saved_scenes_when_old_outputs_are_missing(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")
    import shutil
    shutil.rmtree(tmp_env["outputs"] / "tiny-song")

    r = client_for.get("/api/songs/tiny-song")

    assert r.status_code == 200, r.text
    body = r.json()
    assert [scene["target_text"] for scene in body["scenes"]] == ["la la la", "oh oh oh"]
    assert "shots.json" not in r.text


def test_keyframe_stage_builds_legacy_scene_input_from_saved_records(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")
    import shutil
    shutil.rmtree(tmp_env["outputs"] / "tiny-song")

    r = client_for.post("/api/songs/tiny-song/stages/keyframes")

    assert r.status_code == 200, r.text
    shots = tmp_env["outputs"] / "tiny-song" / "shots.json"
    assert _wait_until(shots.exists)
    data = json.loads(shots.read_text())
    assert [shot["target_text"] for shot in data["shots"]] == ["la la la", "oh oh oh"]


def test_startup_import_does_not_overwrite_saved_scene_edits(tmp_env, fixture_song_one):
    from editor.server.importer import import_all
    from editor.server.store import connection, init_db

    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    init_db(tmp_env["db"])
    import_all(tmp_env["db"], tmp_env["music"], tmp_env["outputs"])
    with connection(tmp_env["db"]) as c:
        c.execute(
            """
            UPDATE scenes
            SET target_text = 'saved corrected words',
                start_s = 9.0,
                end_s = 12.0,
                beat = 'saved beat'
            WHERE scene_index = 1
            """
        )

    shots = tmp_env["outputs"] / "tiny-song" / "shots.json"
    data = json.loads(shots.read_text())
    data["shots"][0]["target_text"] = "old file words"
    data["shots"][0]["start_s"] = 0.0
    data["shots"][0]["end_s"] = 0.3
    shots.write_text(json.dumps(data))
    storyboard = tmp_env["outputs"] / "tiny-song" / "storyboard.json"
    sb = json.loads(storyboard.read_text())
    sb["shots"][0]["beat"] = "old file beat"
    storyboard.write_text(json.dumps(sb))

    import_all(tmp_env["db"], tmp_env["music"], tmp_env["outputs"])

    with connection(tmp_env["db"]) as c:
        row = c.execute(
            "SELECT target_text, start_s, end_s, beat FROM scenes WHERE scene_index = 1",
        ).fetchone()
    assert row["target_text"] == "saved corrected words"
    assert row["start_s"] == 9.0
    assert row["end_s"] == 12.0
    assert row["beat"] == "saved beat"


def test_no_saved_scenes_returns_empty_state_not_old_file_error(client_for, tmp_env):
    wav = tmp_env["music"] / "empty-song.wav"
    wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
    client_for.post("/api/import")

    r = client_for.get("/api/songs/empty-song")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scenes"] == []
    assert body["workflow"]["stages"]["transcription"]["state"] == "available"
    assert "shots.json" not in r.text
