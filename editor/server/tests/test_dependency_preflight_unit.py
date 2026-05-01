"""Story 26 product-level dependency preflight tests."""

from __future__ import annotations

import importlib
import os
import wave
from pathlib import Path

import pytest


def _reload_preflight(monkeypatch, tmp_path: Path):
    db = tmp_path / "editor.db"
    music = tmp_path / "music"
    outputs = tmp_path / "outputs"
    music.mkdir(exist_ok=True)
    outputs.mkdir(exist_ok=True)
    monkeypatch.setenv("EDITOR_DB_PATH", str(db))
    monkeypatch.setenv("EDITOR_MUSIC_DIR", str(music))
    monkeypatch.setenv("EDITOR_OUTPUTS_DIR", str(outputs))
    import editor.server.config as cfg
    import editor.server.pipeline.preflight as preflight
    importlib.reload(cfg)
    return importlib.reload(preflight), music, outputs


def _write_wav(path: Path, duration_s: float = 1.1) -> None:
    framerate = 8000
    frames = int(duration_s * framerate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(framerate)
        wav.writeframes(b"\x00\x00" * frames)


def test_audio_transcribe_reports_missing_audio_before_work(monkeypatch, tmp_path):
    preflight, _music, _outputs = _reload_preflight(monkeypatch, tmp_path)

    result = preflight.preflight_stage(slug="missing", stage="audio-transcribe")

    assert not result.ok
    assert result.missing[-1].code == "audio_missing"
    assert "pocs/" not in result.first_reason


def test_audio_transcribe_reports_missing_configured_product_command(monkeypatch, tmp_path):
    preflight, music, _outputs = _reload_preflight(monkeypatch, tmp_path)
    _write_wav(music / "song.wav")
    monkeypatch.setenv("EDITOR_FAKE_DEMUCS", str(tmp_path / "missing-demucs.py"))

    result = preflight.preflight_stage(slug="song", stage="audio-transcribe")

    assert not result.ok
    assert result.missing[0].code == "demucs_command_missing"
    assert "missing-demucs.py" not in result.missing[0].detail


def test_keyframes_accept_configured_render_provider(monkeypatch, tmp_path):
    preflight, _music, _outputs = _reload_preflight(monkeypatch, tmp_path)
    monkeypatch.setenv("EDITOR_RENDER_PROVIDER", "fake")

    result = preflight.preflight_stage(slug="song", stage="keyframes")

    assert result.ok


def test_keyframes_require_render_provider(monkeypatch, tmp_path):
    preflight, _music, _outputs = _reload_preflight(monkeypatch, tmp_path)
    monkeypatch.delenv("EDITOR_RENDER_PROVIDER", raising=False)

    result = preflight.preflight_stage(slug="song", stage="keyframes")

    assert not result.ok
    assert any(m.code == "renderer_provider_missing" for m in result.missing)


def test_rendering_reports_missing_provider(monkeypatch, tmp_path):
    preflight, _music, _outputs = _reload_preflight(monkeypatch, tmp_path)
    monkeypatch.delenv("EDITOR_RENDER_PROVIDER", raising=False)

    result = preflight.preflight_stage(slug="song", stage="scene-clip")

    assert not result.ok
    assert result.missing[0].code == "renderer_provider_missing"
    assert "pocs/" not in result.missing[0].detail


def test_unknown_stage_returns_typed_failure(monkeypatch, tmp_path):
    preflight, _music, _outputs = _reload_preflight(monkeypatch, tmp_path)

    result = preflight.preflight_stage(slug="song", stage="not-a-stage")  # type: ignore[arg-type]

    assert not result.ok
    assert result.missing[0].code == "unknown_stage"
