"""Regression tests for production audio-transcribe script resolution."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from editor.server.pipeline.audio_transcribe import (
    _resolve_demucs_script,
    _resolve_whisperx_script,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEV_SCRIPT = _REPO_ROOT / "editor" / "web" / "scripts" / "dev.sh"


@pytest.fixture(autouse=True)
def _without_fake_script_overrides(monkeypatch):
    monkeypatch.delenv("EDITOR_FAKE_DEMUCS", raising=False)
    monkeypatch.delenv("EDITOR_FAKE_WHISPERX_TRANSCRIBE", raising=False)


def _load_demucs_wrapper():
    script = _resolve_demucs_script()
    spec = importlib.util.spec_from_file_location("demucs_separate", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_production_audio_transcribe_scripts_exist(monkeypatch):
    demucs_script = _resolve_demucs_script()
    whisperx_script = _resolve_whisperx_script()

    assert demucs_script.exists(), f"demucs script not found at {demucs_script}"
    assert whisperx_script.exists(), f"whisperx transcribe script not found at {whisperx_script}"

    help_result = subprocess.run(
        [sys.executable, str(demucs_script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0
    assert "--audio" in help_result.stdout
    assert "--out" in help_result.stdout


def test_demucs_package_is_available_to_production_wrapper():
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-c",
            "import importlib.util; raise SystemExit(importlib.util.find_spec('demucs') is None)",
        ],
        cwd=_REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_demucs_wrapper_copies_documented_output_layout(tmp_path, monkeypatch):
    wrapper = _load_demucs_wrapper()
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fake wav")
    out = tmp_path / "run" / "vocals.wav"
    seen_cmd: list[str] = []

    def fake_run(cmd, check):  # noqa: ANN001
        assert check is True
        seen_cmd.extend(str(part) for part in cmd)
        work_dir = Path(cmd[cmd.index("-o") + 1])
        model = cmd[cmd.index("-n") + 1]
        produced = work_dir / model / audio.stem / "vocals.wav"
        produced.parent.mkdir(parents=True)
        produced.write_bytes(b"separated vocals")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)

    wrapper.separate_vocals(audio, out)

    assert seen_cmd[:3] == [sys.executable, "-m", "demucs"]
    assert seen_cmd[seen_cmd.index("-n") + 1] == "htdemucs_6s"
    assert seen_cmd[seen_cmd.index("-o") + 1]
    assert out.read_bytes() == b"separated vocals"


def test_demucs_wrapper_returns_nonzero_on_subprocess_failure(
    tmp_path, monkeypatch, capsys,
):
    wrapper = _load_demucs_wrapper()
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fake wav")
    out = tmp_path / "run" / "vocals.wav"

    def fail_run(cmd, check):  # noqa: ANN001
        raise subprocess.CalledProcessError(42, cmd)

    monkeypatch.setattr(wrapper.subprocess, "run", fail_run)

    assert wrapper.main(["--audio", str(audio), "--out", str(out)]) == 1
    assert not out.exists()
    assert "returned non-zero exit status 42" in capsys.readouterr().err


def test_demucs_wrapper_returns_nonzero_when_vocals_missing(
    tmp_path, monkeypatch, capsys,
):
    wrapper = _load_demucs_wrapper()
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fake wav")
    out = tmp_path / "run" / "vocals.wav"

    def fake_run(cmd, check):  # noqa: ANN001
        assert check is True
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)

    assert wrapper.main(["--audio", str(audio), "--out", str(out)]) == 1
    assert not out.exists()
    assert "produced no vocals.wav" in capsys.readouterr().err


def test_dev_launcher_unsets_e2e_fake_script_overrides():
    body = _DEV_SCRIPT.read_text()
    assert "unset EDITOR_FAKE_DEMUCS" in body
    assert "unset EDITOR_FAKE_WHISPERX_TRANSCRIBE" in body
