#!/usr/bin/env python3
"""Developer environment diagnostics for clean checkout onboarding."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    message: str
    affected_workflows: list[str]


@dataclass(frozen=True)
class DiagnosticsReport:
    ok: bool
    mode: str
    repo_root: str
    diagnostics: list[Diagnostic]


def _which(name: str) -> bool:
    return shutil.which(name) is not None


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _path_from_env(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def _load_project_env(root: Path) -> None:
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    from editor.server.env_file import load_project_env

    load_project_env(root)


def check_dev_environment(root: Path, *, mode: str = "dev") -> DiagnosticsReport:
    root = root.resolve()
    _load_project_env(root)
    diagnostics: list[Diagnostic] = []

    required_tools = {
        "uv": ["python backend", "dependency install", "server tests"],
        "bun": ["frontend install", "frontend dev server", "browser tests"],
        "ffmpeg": ["audio/video playback", "true product rendering"],
    }
    for tool, workflows in required_tools.items():
        if not _which(tool):
            diagnostics.append(Diagnostic(
                code=f"missing_tool_{tool}",
                severity="error",
                message=f"Required command '{tool}' is not on PATH.",
                affected_workflows=workflows,
            ))

    if sys.platform != "darwin" or platform.machine().lower() not in {"arm64", "aarch64"}:
        diagnostics.append(Diagnostic(
            code="unsupported_platform",
            severity="warning",
            message="Real video generation is developed for Apple Silicon macOS; other platforms may run tests but not every product workflow.",
            affected_workflows=["true product rendering", "local model execution"],
        ))

    if not (root / "editor" / "web" / "node_modules").exists():
        diagnostics.append(Diagnostic(
            code="frontend_dependencies_missing",
            severity="warning",
            message="Frontend dependencies are not installed; run 'cd editor/web && bun install'.",
            affected_workflows=["frontend dev server", "browser tests"],
        ))

    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("EDITOR_GENERATION_PROVIDER")):
        diagnostics.append(Diagnostic(
            code="generation_provider_missing",
            severity="warning",
            message="No GEMINI_API_KEY or EDITOR_GENERATION_PROVIDER is configured; generation actions will be blocked.",
            affected_workflows=["world generation", "storyboard generation", "image prompt generation"],
        ))

    if not os.environ.get("EDITOR_RENDER_PROVIDER"):
        diagnostics.append(Diagnostic(
            code="render_provider_missing",
            severity="warning",
            message="No EDITOR_RENDER_PROVIDER is configured; rendering actions will be blocked until a product adapter is configured.",
            affected_workflows=["keyframe rendering", "clip rendering", "final video rendering"],
        ))

    if not list((root / "music").glob("*.wav")):
        diagnostics.append(Diagnostic(
            code="no_local_songs",
            severity="warning",
            message="No local .wav files found in music/; add a .wav and matching .txt lyrics file to import a song.",
            affected_workflows=["editor first run", "song import"],
        ))

    if mode == "test":
        required_env = {
            "EDITOR_DB_PATH": "test database",
            "EDITOR_MUSIC_DIR": "test music root",
            "EDITOR_OUTPUTS_DIR": "test outputs root",
        }
        for env_name, workflow in required_env.items():
            value = _path_from_env(env_name)
            if value is None:
                diagnostics.append(Diagnostic(
                    code=f"missing_{env_name.lower()}",
                    severity="error",
                    message=f"{env_name} must be set for isolated test runs.",
                    affected_workflows=[workflow, "test data isolation"],
                ))
                continue
            unsafe_roots = [root / "music", root / "editor" / "data", root / "pocs"]
            if any(_under(value, unsafe) for unsafe in unsafe_roots):
                diagnostics.append(Diagnostic(
                    code=f"unsafe_{env_name.lower()}",
                    severity="error",
                    message=f"{env_name} points at development data ({value}); use a temp test directory.",
                    affected_workflows=[workflow, "test data isolation"],
                ))

    ok = not any(d.severity == "error" for d in diagnostics)
    return DiagnosticsReport(ok=ok, mode=mode, repo_root=str(root), diagnostics=diagnostics)


def _format_text(report: DiagnosticsReport) -> str:
    lines = [
        f"macvideo diagnostics ({report.mode})",
        f"repo: {report.repo_root}",
        f"status: {'ok' if report.ok else 'blocked'}",
    ]
    if not report.diagnostics:
        lines.append("no issues found")
    for diag in report.diagnostics:
        workflows = ", ".join(diag.affected_workflows)
        lines.append(f"[{diag.severity}] {diag.code}: {diag.message} ({workflows})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--mode", choices=["dev", "test"], default="dev")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = check_dev_environment(args.root, mode=args.mode)
    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(_format_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
