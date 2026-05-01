"""Story 31 onboarding diagnostics tests."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_dev_environment.py"
_SPEC = importlib.util.spec_from_file_location("check_dev_environment", _SCRIPT)
assert _SPEC and _SPEC.loader
diagnostics = importlib.util.module_from_spec(_SPEC)
sys.modules["check_dev_environment"] = diagnostics
_SPEC.loader.exec_module(diagnostics)


def _fake_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "editor" / "web" / "node_modules").mkdir(parents=True)
    (root / "music").mkdir()
    (root / "music" / "sample.wav").write_bytes(b"RIFF")
    return root


def _fake_path(tmp_path: Path, monkeypatch, *, missing: set[str] | None = None) -> None:
    missing = missing or set()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("uv", "bun", "ffmpeg"):
        if name in missing:
            continue
        tool = bin_dir / name
        tool.write_text("#!/usr/bin/env sh\nexit 0\n")
        tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))


def test_dev_diagnostics_pass_with_required_tools_and_warn_for_optional_models(tmp_path, monkeypatch):
    root = _fake_root(tmp_path)
    _fake_path(tmp_path, monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("EDITOR_GENERATION_PROVIDER", raising=False)
    monkeypatch.delenv("EDITOR_RENDER_PROVIDER", raising=False)

    report = diagnostics.check_dev_environment(root, mode="dev")

    assert report.ok is True
    codes = {d.code for d in report.diagnostics}
    assert "generation_provider_missing" in codes
    assert "render_provider_missing" in codes


def test_dev_diagnostics_fail_for_missing_required_tool(tmp_path, monkeypatch):
    root = _fake_root(tmp_path)
    _fake_path(tmp_path, monkeypatch, missing={"bun"})
    monkeypatch.setenv("EDITOR_GENERATION_PROVIDER", "fake")
    monkeypatch.setenv("EDITOR_RENDER_PROVIDER", "fake")

    report = diagnostics.check_dev_environment(root, mode="dev")

    assert report.ok is False
    assert any(d.code == "missing_tool_bun" for d in report.diagnostics)


def test_dev_diagnostics_reports_no_song_empty_checkout(tmp_path, monkeypatch):
    root = _fake_root(tmp_path)
    for wav in (root / "music").glob("*.wav"):
        wav.unlink()
    _fake_path(tmp_path, monkeypatch)
    monkeypatch.setenv("EDITOR_GENERATION_PROVIDER", "fake")
    monkeypatch.setenv("EDITOR_RENDER_PROVIDER", "fake")

    report = diagnostics.check_dev_environment(root, mode="dev")

    assert report.ok is True
    assert any(d.code == "no_local_songs" for d in report.diagnostics)


def test_dev_diagnostics_reports_unsupported_platform(tmp_path, monkeypatch):
    root = _fake_root(tmp_path)
    _fake_path(tmp_path, monkeypatch)
    monkeypatch.setenv("EDITOR_GENERATION_PROVIDER", "fake")
    monkeypatch.setenv("EDITOR_RENDER_PROVIDER", "fake")
    monkeypatch.setattr(diagnostics.sys, "platform", "linux")
    monkeypatch.setattr(diagnostics.platform, "machine", lambda: "x86_64")

    report = diagnostics.check_dev_environment(root, mode="dev")

    assert report.ok is True
    assert any(d.code == "unsupported_platform" for d in report.diagnostics)


def test_test_mode_rejects_development_data_paths(tmp_path, monkeypatch):
    root = _fake_root(tmp_path)
    _fake_path(tmp_path, monkeypatch)
    monkeypatch.setenv("EDITOR_GENERATION_PROVIDER", "fake")
    monkeypatch.setenv("EDITOR_RENDER_PROVIDER", "fake")
    monkeypatch.setenv("EDITOR_DB_PATH", str(root / "editor" / "data" / "editor.db"))
    monkeypatch.setenv("EDITOR_MUSIC_DIR", str(root / "music"))
    monkeypatch.setenv("EDITOR_OUTPUTS_DIR", str(root / "pocs" / "29-full-song" / "outputs"))

    report = diagnostics.check_dev_environment(root, mode="test")

    assert report.ok is False
    assert {d.code for d in report.diagnostics} >= {
        "unsafe_editor_db_path",
        "unsafe_editor_music_dir",
        "unsafe_editor_outputs_dir",
    }


def test_test_mode_accepts_isolated_temp_data_paths(tmp_path, monkeypatch):
    root = _fake_root(tmp_path)
    isolated = tmp_path / "isolated"
    _fake_path(tmp_path, monkeypatch)
    monkeypatch.setenv("EDITOR_GENERATION_PROVIDER", "fake")
    monkeypatch.setenv("EDITOR_RENDER_PROVIDER", "fake")
    monkeypatch.setenv("EDITOR_DB_PATH", str(isolated / "editor.db"))
    monkeypatch.setenv("EDITOR_MUSIC_DIR", str(isolated / "music"))
    monkeypatch.setenv("EDITOR_OUTPUTS_DIR", str(isolated / "outputs"))

    report = diagnostics.check_dev_environment(root, mode="test")

    assert report.ok is True
    assert not any(d.code.startswith("unsafe_") for d in report.diagnostics)


def test_cli_json_reports_blocking_status(tmp_path, monkeypatch, capsys):
    root = _fake_root(tmp_path)
    _fake_path(tmp_path, monkeypatch, missing={"ffmpeg"})
    monkeypatch.setattr(os, "environ", os.environ)

    code = diagnostics.main(["--root", str(root), "--mode", "dev", "--json"])

    assert code == 1
    assert '"missing_tool_ffmpeg"' in capsys.readouterr().out
