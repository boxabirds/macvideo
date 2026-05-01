"""Story 26 API integration tests for dependency preflight."""

from __future__ import annotations

import wave


def _write_wav(path, duration_s: float = 1.2) -> None:
    framerate = 8000
    frames = int(duration_s * framerate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(framerate)
        wav.writeframes(b"\x00\x00" * frames)


def test_stage_preflight_blocks_missing_generation_command_before_run(
    client_for, tmp_env, fixture_song_one, monkeypatch,
):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")
    monkeypatch.setenv("EDITOR_FAKE_GEN_KEYFRAMES", str(tmp_env["root"] / "missing.py"))

    r = client_for.post("/api/songs/tiny-song/stages/keyframes")

    assert r.status_code == 422
    body = r.json()["detail"]
    assert body["code"] == "dependency_preflight_failed"
    assert body["missing"][0]["code"] == "generation_command_missing"
    assert "pocs/" not in body["reason"]
    assert "missing.py" not in body["reason"]

    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        count = c.execute("SELECT COUNT(*) FROM regen_runs").fetchone()[0]
    assert count == 0


def test_stage_preflight_allows_valid_fake_generation_command(
    client_for, tmp_env, fixture_song_one,
):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    r = client_for.post("/api/songs/tiny-song/stages/keyframes")

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"


def test_audio_transcribe_preflight_blocks_missing_configured_command(
    client_for, tmp_env, monkeypatch,
):
    slug = "preflight-audio"
    _write_wav(tmp_env["music"] / f"{slug}.wav")
    client_for.post("/api/import")
    monkeypatch.setenv("EDITOR_FAKE_DEMUCS", str(tmp_env["root"] / "missing-demucs.py"))

    r = client_for.post(f"/api/songs/{slug}/audio-transcribe")

    assert r.status_code == 422
    body = r.json()["detail"]
    assert body["code"] == "dependency_preflight_failed"
    assert body["missing"][0]["code"] == "demucs_command_missing"
    assert "missing-demucs.py" not in body["reason"]


def test_scene_regen_preflight_blocks_missing_render_command(
    client_for, tmp_env, fixture_song_one, monkeypatch,
):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")
    monkeypatch.setenv("EDITOR_FAKE_RENDER_CLIPS", str(tmp_env["root"] / "missing-render.py"))

    r = client_for.post(
        "/api/songs/tiny-song/scenes/1/takes",
        json={"artefact_kind": "clip", "trigger": "regen"},
    )

    assert r.status_code == 422
    body = r.json()["detail"]
    assert body["code"] == "dependency_preflight_failed"
    assert body["missing"][0]["code"] == "render_command_missing"
    assert "pocs/" not in body["reason"]
