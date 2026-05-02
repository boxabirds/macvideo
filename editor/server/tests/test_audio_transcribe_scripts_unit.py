"""Regression tests for production audio-transcribe script resolution."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import wave
from pathlib import Path

import pytest

from editor.server.pipeline.audio_transcribe import (
    _resolve_demucs_script,
    _resolve_whisperx_invocation,
    _resolve_whisperx_script,
    run_audio_transcribe,
)
from editor.server.pipeline.paths import resolve_song_paths

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEV_SCRIPT = _REPO_ROOT / "editor" / "web" / "scripts" / "dev.sh"
_START_EDITOR_SCRIPT = _REPO_ROOT / "scripts" / "start_editor.sh"
_E2E_BACKEND_SCRIPT = _REPO_ROOT / "editor" / "web" / "tests" / "e2e" / "setup_backend.sh"
_TESTS_DIR = Path(__file__).resolve().parent
_FAKE_DEMUCS = _TESTS_DIR / "fake_scripts" / "fake_demucs.py"


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


def _write_silent_wav(path: Path, *, duration_s: float = 0.1) -> None:
    sample_rate = 16000
    n_frames = int(sample_rate * duration_s)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * n_frames)


def _write_fake_whisperx_module(path: Path) -> None:
    path.write_text(
        """
class _Model:
    def transcribe(self, audio, batch_size, language):
        return {
            "segments": [
                {"text": "product wrapper segment", "start": 0.0, "end": 1.2},
            ],
        }


def load_model(model_name, device, compute_type, vad_options):
    assert model_name == "large-v3"
    assert device == "cpu"
    assert compute_type == "float32"
    assert vad_options == {"vad_onset": 0.35, "vad_offset": 0.25}
    return _Model()


def load_audio(path):
    return {"path": path}
""".lstrip()
    )


def test_production_audio_transcribe_scripts_exist(monkeypatch):
    demucs_script = _resolve_demucs_script()
    whisperx_script = _resolve_whisperx_script()

    assert demucs_script.exists(), f"demucs script not found at {demucs_script}"
    assert whisperx_script.exists(), f"whisperx transcribe script not found at {whisperx_script}"
    assert whisperx_script == (
        _REPO_ROOT / "editor" / "server" / "pipeline" / "scripts" / "whisperx_transcribe.py"
    )
    assert "experiments" not in whisperx_script.parts

    help_result = subprocess.run(
        [sys.executable, str(demucs_script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0
    assert "--audio" in help_result.stdout
    assert "--out" in help_result.stdout

    wx_help = subprocess.run(
        [sys.executable, str(whisperx_script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert wx_help.returncode == 0
    assert "--audio" in wx_help.stdout
    assert "--out" in wx_help.stdout
    assert "transcribe_whisperx_noprompt" not in wx_help.stdout + wx_help.stderr


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


def test_product_whisperx_invocation_uses_stable_flag_contract(tmp_path):
    vocals = tmp_path / "vocals.wav"
    out = tmp_path / "segments.json"

    script, args = _resolve_whisperx_invocation(vocals, out)

    assert script == _resolve_whisperx_script()
    assert "experiments" not in script.parts
    assert args == ["--audio", str(vocals), "--out", str(out)]


def test_fake_whisperx_invocation_uses_flag_contract(tmp_path, monkeypatch):
    fake = tmp_path / "fake_whisperx.py"
    fake.write_text("#!/usr/bin/env python\n")
    monkeypatch.setenv("EDITOR_FAKE_WHISPERX_TRANSCRIBE", str(fake))
    vocals = tmp_path / "vocals.wav"
    out = tmp_path / "segments.json"

    script, args = _resolve_whisperx_invocation(vocals, out)

    assert script == fake
    assert args == ["--audio", str(vocals), "--out", str(out)]


def test_product_whisperx_wrapper_transcribes_with_owned_cli(tmp_path, monkeypatch):
    script = _resolve_whisperx_script()
    assert "experiments" not in script.parts

    fake_module_dir = tmp_path / "fake_module"
    fake_module_dir.mkdir()
    _write_fake_whisperx_module(fake_module_dir / "whisperx.py")
    monkeypatch.setenv("PYTHONPATH", str(fake_module_dir))

    vocals = tmp_path / "vocals.wav"
    out = tmp_path / "segments.json"
    _write_silent_wav(vocals)

    result = subprocess.run(
        [sys.executable, str(script), "--audio", str(vocals), "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Usage:" not in result.stderr
    assert "transcribe_whisperx_noprompt" not in result.stderr
    assert '"method": "whisperx_transcribe"' in out.read_text()
    assert "product wrapper segment" in out.read_text()


def test_run_audio_transcribe_uses_product_whisperx_without_poc_usage(
    tmp_env, tmp_path, monkeypatch,
):
    script = _resolve_whisperx_script()
    assert script.exists()
    assert "experiments" not in script.parts

    fake_module_dir = tmp_path / "fake_module"
    fake_module_dir.mkdir()
    _write_fake_whisperx_module(fake_module_dir / "whisperx.py")
    monkeypatch.setenv("PYTHONPATH", str(fake_module_dir))
    monkeypatch.setenv("EDITOR_FAKE_DEMUCS", str(_FAKE_DEMUCS))

    slug = "product-whisperx-runtime"
    _write_silent_wav(tmp_env["music"] / f"{slug}.wav")
    paths = resolve_song_paths(
        outputs_root=tmp_env["outputs"],
        music_root=tmp_env["music"],
        slug=slug,
    )
    paths.run_dir.mkdir(parents=True, exist_ok=True)

    result = run_audio_transcribe(
        slug=slug,
        paths=paths,
        run_id=991,
        force=False,
    )

    assert result.ok is True, result.stderr_tail
    assert result.segments == [
        {"text": "product wrapper segment", "start": 0.0, "end": 1.2},
    ]
    assert "Usage:" not in result.stderr_tail
    assert "transcribe_whisperx_noprompt" not in result.stderr_tail


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


def test_dev_launcher_scopes_fake_script_removal_to_backend_command():
    launcher = _DEV_SCRIPT.read_text()
    body = _START_EDITOR_SCRIPT.read_text()
    assert "scripts/start_editor.sh" in launcher
    assert "unset EDITOR_FAKE_DEMUCS" not in body
    assert "unset EDITOR_FAKE_WHISPERX_TRANSCRIBE" not in body
    assert "-u EDITOR_FAKE_DEMUCS" in body
    assert "-u EDITOR_FAKE_WHISPERX_TRANSCRIBE" in body
    assert '"${BACKEND_ENV[@]}" uv run uvicorn' in body


def test_e2e_backend_launcher_does_not_inject_fake_scripts():
    body = _E2E_BACKEND_SCRIPT.read_text()
    assert "EDITOR_FAKE_GEN_KEYFRAMES" not in body
    assert "EDITOR_FAKE_RENDER_CLIPS" not in body
    assert "EDITOR_FAKE_WHISPERX_ALIGN" not in body
    assert "EDITOR_FAKE_DEMUCS" not in body
    assert "EDITOR_FAKE_WHISPERX_TRANSCRIBE" not in body
    assert "exec env \\" in body
    assert "uv run uvicorn editor.server.main:app" in body
