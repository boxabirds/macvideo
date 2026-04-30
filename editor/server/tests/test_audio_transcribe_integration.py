"""Story 18 — integration tests for run_audio_transcribe.

Covers the seven cases enumerated in the design's
lyrics.audio-transcribe-pipeline capability:
  1. success path (Story 18: returns segments, no lyrics.txt)
  2. Demucs failure
  3. WhisperX failure
  4. cancellation pre-Demucs
  5. cancellation mid-Demucs
  6. cancellation mid-WhisperX
  7. cancellation after success (Story 18: segments not returned)

Uses fake subprocess scripts under tests/fake_scripts/ so the suite runs in
seconds instead of the multi-minute real-Demucs+WhisperX pipeline.
"""

from __future__ import annotations

import threading
import time
import wave
from pathlib import Path

import pytest

from editor.server.pipeline.audio_transcribe import (
    PHASE_SEPARATING_VOCALS, PHASE_TRANSCRIBING, run_audio_transcribe,
)
from editor.server.pipeline.paths import resolve_song_paths


_TESTS_DIR = Path(__file__).resolve().parent
_FAKE_DEMUCS = _TESTS_DIR / "fake_scripts" / "fake_demucs.py"
_FAKE_WHISPERX_T = _TESTS_DIR / "fake_scripts" / "fake_whisperx_transcribe.py"

_SLUG = "audio-transcribe-test"
_WAV_SR = 16000
_WAV_DURATION_S = 2


def _write_silent_wav(path: Path, duration_s: float = _WAV_DURATION_S) -> None:
    n_frames = int(_WAV_SR * duration_s)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_WAV_SR)
        w.writeframes(b"\x00\x00" * n_frames)


@pytest.fixture
def env(tmp_env, monkeypatch):
    monkeypatch.setenv("EDITOR_FAKE_DEMUCS", str(_FAKE_DEMUCS))
    monkeypatch.setenv("EDITOR_FAKE_WHISPERX_TRANSCRIBE", str(_FAKE_WHISPERX_T))
    music = tmp_env["music"]
    outputs = tmp_env["outputs"]
    _write_silent_wav(music / f"{_SLUG}.wav")
    paths = resolve_song_paths(
        outputs_root=outputs, music_root=music, slug=_SLUG,
    )
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    return {"paths": paths, "music": music, "outputs": outputs}


# ---------- 1. success path -------------------------------------------------

def test_success_writes_lyrics_and_phase_durations(env):
    """Story 18: no lyrics.txt written. Segments returned in result."""
    progress: list[tuple[str, float]] = []
    res = run_audio_transcribe(
        slug=_SLUG, paths=env["paths"], run_id=101, force=False,
        progress_cb=lambda p, pct: progress.append((p, pct)),
    )
    assert res.ok is True
    assert res.cancelled is False
    # Story 18: segments returned instead of lyrics path.
    assert len(res.segments) == 3
    assert res.segments[0]["text"] == "this is a fake segment"
    # No lyrics file written.
    assert not env["paths"].lyrics_txt.exists()
    # vocals.wav was written into the run dir.
    assert (env["paths"].run_dir / "vocals.wav").exists()
    # Both phases reported.
    assert PHASE_SEPARATING_VOCALS in res.phase_durations
    assert PHASE_TRANSCRIBING in res.phase_durations
    # Progress callback received both phase opens.
    phases_seen = {p for p, _ in progress}
    assert PHASE_SEPARATING_VOCALS in phases_seen
    assert PHASE_TRANSCRIBING in phases_seen


# ---------- 2. Demucs failure ----------------------------------------------

def test_demucs_failure_returns_not_ok_no_lyrics(env, monkeypatch):
    monkeypatch.setenv("FAKE_DEMUCS_FAIL", "1")
    res = run_audio_transcribe(
        slug=_SLUG, paths=env["paths"], run_id=102, force=False,
    )
    assert res.ok is False
    assert res.failing_phase == PHASE_SEPARATING_VOCALS
    assert res.returncode != 0
    assert "forced failure" in res.stderr_tail
    assert not env["paths"].lyrics_txt.exists()


# ---------- 3. WhisperX failure --------------------------------------------

def test_whisperx_failure_returns_not_ok_no_lyrics(env, monkeypatch):
    monkeypatch.setenv("FAKE_WHISPERX_FAIL", "1")
    res = run_audio_transcribe(
        slug=_SLUG, paths=env["paths"], run_id=103, force=False,
    )
    assert res.ok is False
    assert res.failing_phase == PHASE_TRANSCRIBING
    # Demucs ran first → vocals.wav remains for diagnostics.
    assert (env["paths"].run_dir / "vocals.wav").exists()
    assert not env["paths"].lyrics_txt.exists()


# ---------- 4. cancellation pre-Demucs --------------------------------------

def test_cancel_pre_demucs_no_subprocess_no_lyrics(env):
    cancel = threading.Event()
    cancel.set()  # already cancelled at entry
    res = run_audio_transcribe(
        slug=_SLUG, paths=env["paths"], run_id=104, force=False,
        cancel_event=cancel,
    )
    assert res.cancelled is True
    assert res.ok is True  # cancel is not a failure
    # No subprocess ran → no vocals.wav, no lyrics.
    assert not (env["paths"].run_dir / "vocals.wav").exists()
    assert not env["paths"].lyrics_txt.exists()


# ---------- 5. cancellation mid-Demucs --------------------------------------

def test_cancel_mid_demucs_partial_vocals_removed(env, monkeypatch):
    # Make Demucs sleep 1s while writing partial output, fire cancel mid-flight.
    monkeypatch.setenv("FAKE_DEMUCS_DELAY_S", "1.5")
    monkeypatch.setenv("FAKE_DEMUCS_PARTIAL", "1")
    cancel = threading.Event()

    def _trip_cancel() -> None:
        time.sleep(0.3)
        cancel.set()
    threading.Thread(target=_trip_cancel, daemon=True).start()

    res = run_audio_transcribe(
        slug=_SLUG, paths=env["paths"], run_id=105, force=False,
        cancel_event=cancel,
    )
    assert res.cancelled is True
    assert not (env["paths"].run_dir / "vocals.wav").exists()
    assert not env["paths"].lyrics_txt.exists()


# ---------- 6. cancellation mid-WhisperX -----------------------------------

def test_cancel_mid_whisperx_keeps_vocals_no_lyrics(env, monkeypatch):
    # Demucs is fast; WhisperX sleeps 1.5s. Cancel during phase 2.
    monkeypatch.setenv("FAKE_WHISPERX_DELAY_S", "1.5")
    monkeypatch.setenv("FAKE_WHISPERX_PARTIAL", "1")
    cancel = threading.Event()

    def _trip_cancel() -> None:
        # Wait for Demucs to finish, then cancel during WhisperX.
        time.sleep(0.5)
        cancel.set()
    threading.Thread(target=_trip_cancel, daemon=True).start()

    res = run_audio_transcribe(
        slug=_SLUG, paths=env["paths"], run_id=106, force=False,
        cancel_event=cancel,
    )
    assert res.cancelled is True
    # vocals.wav stays — phase 1 completed; alignment may reuse it.
    assert (env["paths"].run_dir / "vocals.wav").exists()
    assert not env["paths"].lyrics_txt.exists()
    # Temp transcript dir was cleaned up — only the vocals.wav remains in run_dir.
    leftovers = [p for p in env["paths"].run_dir.iterdir()
                 if p.name != "vocals.wav"]
    assert leftovers == []


# ---------- 7. cancellation after success (race window) --------------------

def test_cancel_after_whisperx_before_write_no_lyrics(env, monkeypatch):
    """Story 18: cancel event fires AFTER WhisperX exited ok but BEFORE the
    orchestrator returns segments. The design contract says no segments MUST
    be returned in this window — cancel takes priority over commit.
    """
    cancel = threading.Event()

    monkeypatch.setenv("FAKE_WHISPERX_DELAY_S", "0.5")

    def _trip_cancel() -> None:
        time.sleep(0.4)
        cancel.set()
    threading.Thread(target=_trip_cancel, daemon=True).start()

    res = run_audio_transcribe(
        slug=_SLUG, paths=env["paths"], run_id=107, force=False,
        cancel_event=cancel,
    )
    assert res.cancelled is True
    # Story 18: no segments returned when cancelled.
    assert len(res.segments) == 0
    assert not env["paths"].lyrics_txt.exists()
