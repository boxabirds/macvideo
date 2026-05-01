"""Story 26 architecture boundary checks."""

from __future__ import annotations

import json
from pathlib import Path

from editor.server.architecture.boundary import scan_runtime_boundaries


def _write_inventory(root: Path, entries: list[dict]) -> None:
    docs = root / "docs" / "architecture"
    docs.mkdir(parents=True)
    (docs / "temporary-legacy-dependencies.json").write_text(json.dumps({
        "version": 1,
        "entries": entries,
    }))


def test_boundary_scanner_flags_uninventoried_runtime_references(tmp_path):
    runtime = tmp_path / "editor" / "server"
    runtime.mkdir(parents=True)
    (runtime / "bad.py").write_text(
        "from editor.server.pipeline.paths import poc_scripts_root\n"
        "SCRIPT = 'pocs/29-full-song/scripts/gen_keyframes.py'\n"
    )
    _write_inventory(tmp_path, [])

    violations = scan_runtime_boundaries(tmp_path)

    assert violations
    assert {v.path for v in violations} == {"editor/server/bad.py"}
    assert any(v.token == "poc_scripts_root" for v in violations)


def test_boundary_scanner_accepts_complete_temporary_inventory(tmp_path):
    runtime = tmp_path / "editor" / "server"
    runtime.mkdir(parents=True)
    (runtime / "legacy.py").write_text("SCRIPT = 'gen_keyframes.py'\n")
    _write_inventory(tmp_path, [{
        "path": "editor/server/legacy.py",
        "owner_story": 30,
        "workflow": "generation",
        "reason_remaining": "generation services are not product-owned yet",
        "removal_condition": "story 30 replaces the legacy generation runner",
    }])

    assert scan_runtime_boundaries(tmp_path) == []


def test_boundary_scanner_fails_incomplete_inventory_entries(tmp_path):
    runtime = tmp_path / "editor" / "server"
    runtime.mkdir(parents=True)
    (runtime / "legacy.py").write_text("SCRIPT = 'render_clips.py'\n")
    _write_inventory(tmp_path, [{
        "path": "editor/server/legacy.py",
        "owner_story": 28,
        "workflow": "",
        "reason_remaining": "rendering is still legacy",
        "removal_condition": "story 28 replaces rendering",
    }])

    violations = scan_runtime_boundaries(tmp_path)

    assert len(violations) == 2
    assert all(v.path == "editor/server/legacy.py" for v in violations)


def test_repository_runtime_references_are_inventoried():
    repo_root = Path(__file__).resolve().parents[3]

    violations = scan_runtime_boundaries(repo_root)

    assert violations == []

