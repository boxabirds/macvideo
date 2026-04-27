"""Story 14 — integration tests for POST /api/songs/{slug}/audio-transcribe.

Covers all 9 cases from the design's lyrics.transcribe-endpoint capability
Tests subsection. Uses the fake Demucs/WhisperX scripts from task 14.1
so the suite runs in seconds.
"""

from __future__ import annotations

import time
import wave
from pathlib import Path

import pytest


_TESTS_DIR = Path(__file__).resolve().parent
_FAKE_DEMUCS = _TESTS_DIR / "fake_scripts" / "fake_demucs.py"
_FAKE_WHISPERX_T = _TESTS_DIR / "fake_scripts" / "fake_whisperx_transcribe.py"

_SLUG = "audio-transcribe-api-test"
_WAV_SR = 16000


def _write_silent_wav(path: Path, duration_s: float) -> None:
    n_frames = int(_WAV_SR * duration_s)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_WAV_SR)
        w.writeframes(b"\x00\x00" * n_frames)


def _wait_until(fn, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def fresh_song_with_audio(client_for, tmp_env, monkeypatch):
    """Create a song row whose audio file is present but lyrics is missing."""
    monkeypatch.setenv("EDITOR_FAKE_DEMUCS", str(_FAKE_DEMUCS))
    monkeypatch.setenv("EDITOR_FAKE_WHISPERX_TRANSCRIBE", str(_FAKE_WHISPERX_T))
    music = tmp_env["music"]
    _write_silent_wav(music / f"{_SLUG}.wav", duration_s=2.0)
    # Trigger an import so the songs row exists with audio metadata.
    client_for.post("/api/import")
    return {"slug": _SLUG, "tmp_env": tmp_env}


# ---------- 1. happy path: 200, run row created, scope correct ------------

def test_post_accepts_fresh_song_returns_run_id(client_for, fresh_song_with_audio):
    slug = fresh_song_with_audio["slug"]
    r = client_for.post(f"/api/songs/{slug}/audio-transcribe")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "run_id" in body and isinstance(body["run_id"], int)
    assert body["status"] == "pending"

    # Verify the regen_runs row landed with the right scope.
    from editor.server.store import connection
    with connection(fresh_song_with_audio["tmp_env"]["db"]) as c:
        row = c.execute(
            "SELECT scope FROM regen_runs WHERE id = ?", (body["run_id"],),
        ).fetchone()
    assert row is not None
    assert row["scope"] == "stage_audio_transcribe"


# ---------- 2. existing lyrics + force=true → 200 -------------------------

def test_post_existing_lyrics_force_true_starts(client_for, fresh_song_with_audio):
    slug = fresh_song_with_audio["slug"]
    music = fresh_song_with_audio["tmp_env"]["music"]
    (music / f"{slug}.txt").write_text("pre-existing lyrics\n")
    r = client_for.post(f"/api/songs/{slug}/audio-transcribe?force=true")
    assert r.status_code == 200, r.text


# ---------- 3. existing lyrics + force=false → 409 overwrite_required ----

def test_post_existing_lyrics_force_false_409(client_for, fresh_song_with_audio):
    slug = fresh_song_with_audio["slug"]
    music = fresh_song_with_audio["tmp_env"]["music"]
    (music / f"{slug}.txt").write_text("pre-existing lyrics\n")
    r = client_for.post(f"/api/songs/{slug}/audio-transcribe")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "overwrite_required"


# ---------- 4. cross-stage single-flight: stage_audio_transcribe blocks ---

def test_post_blocks_on_existing_audio_transcribe_run(client_for, fresh_song_with_audio):
    slug = fresh_song_with_audio["slug"]
    # Insert a pending stage_audio_transcribe row directly so we can assert
    # the conflict path without depending on race timing of the background
    # task.
    from editor.server.store import connection
    with connection(fresh_song_with_audio["tmp_env"]["db"]) as c:
        song_id = c.execute("SELECT id FROM songs WHERE slug = ?", (slug,)).fetchone()["id"]
        c.execute(
            "INSERT INTO regen_runs (scope, song_id, status, created_at) "
            "VALUES ('stage_audio_transcribe', ?, 'pending', strftime('%s', 'now'))",
            (song_id,),
        )
    r = client_for.post(f"/api/songs/{slug}/audio-transcribe?force=true")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "single_flight_conflict"


# ---------- 5. cross-stage block: stage_transcribe also blocks ------------

def test_post_blocks_on_existing_transcribe_run(client_for, fresh_song_with_audio):
    slug = fresh_song_with_audio["slug"]
    from editor.server.store import connection
    with connection(fresh_song_with_audio["tmp_env"]["db"]) as c:
        song_id = c.execute("SELECT id FROM songs WHERE slug = ?", (slug,)).fetchone()["id"]
        c.execute(
            "INSERT INTO regen_runs (scope, song_id, status, created_at) "
            "VALUES ('stage_transcribe', ?, 'pending', strftime('%s', 'now'))",
            (song_id,),
        )
    r = client_for.post(f"/api/songs/{slug}/audio-transcribe?force=true")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "single_flight_conflict"


# ---------- 6. audio_missing → 422 ----------------------------------------

def test_post_audio_missing_422(client_for, fresh_song_with_audio):
    slug = fresh_song_with_audio["slug"]
    music = fresh_song_with_audio["tmp_env"]["music"]
    (music / f"{slug}.wav").unlink()
    r = client_for.post(f"/api/songs/{slug}/audio-transcribe")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "audio_missing"


# ---------- 7. audio_too_short → 422 --------------------------------------

def test_post_audio_too_short_422(client_for, fresh_song_with_audio):
    slug = fresh_song_with_audio["slug"]
    music = fresh_song_with_audio["tmp_env"]["music"]
    _write_silent_wav(music / f"{slug}.wav", duration_s=0.1)
    r = client_for.post(f"/api/songs/{slug}/audio-transcribe")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "audio_too_short"


# ---------- 8. unknown slug → 404 -----------------------------------------

def test_post_unknown_slug_404(client_for, tmp_env, monkeypatch):
    monkeypatch.setenv("EDITOR_FAKE_DEMUCS", str(_FAKE_DEMUCS))
    monkeypatch.setenv("EDITOR_FAKE_WHISPERX_TRANSCRIBE", str(_FAKE_WHISPERX_T))
    r = client_for.post("/api/songs/never-imported/audio-transcribe")
    assert r.status_code == 404


# ---------- 9. happy path completes: lyrics file lands -------------------

def test_post_writes_lyrics_after_run_completes(client_for, fresh_song_with_audio):
    slug = fresh_song_with_audio["slug"]
    music = fresh_song_with_audio["tmp_env"]["music"]
    lyrics_path = music / f"{slug}.txt"
    assert not lyrics_path.exists()

    r = client_for.post(f"/api/songs/{slug}/audio-transcribe")
    assert r.status_code == 200

    # Wait for the orchestrator to finish writing the lyrics file. The
    # full alignment phase needs whisperx_align (the existing Story 12
    # script) too, which is fake-able via EDITOR_FAKE_WHISPERX_ALIGN —
    # for THIS test we only verify the audio-transcribe phase wrote
    # the lyrics file. Phase 3 (alignment) will fail because the fake
    # for whisperx_align isn't wired here; that's a separate concern.
    assert _wait_until(lyrics_path.exists, timeout=5.0)
    assert "fake transcript" in lyrics_path.read_text()
