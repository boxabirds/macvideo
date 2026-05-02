"""Architecture boundary checks."""

from __future__ import annotations

from pathlib import Path

from editor.server.architecture.boundary import FORBIDDEN_TOKENS, scan_runtime_boundaries


def test_boundary_scanner_flags_forbidden_runtime_references(tmp_path):
    runtime = tmp_path / "editor" / "server"
    runtime.mkdir(parents=True)
    (runtime / "bad.py").write_text(
        f"SCRIPT_ROOT = {FORBIDDEN_TOKENS[2]!r}\n"
        f"SCRIPT = {FORBIDDEN_TOKENS[1] + '/scripts/' + FORBIDDEN_TOKENS[3]!r}\n"
    )

    violations = scan_runtime_boundaries(tmp_path)

    assert violations
    assert {v.path for v in violations} == {"editor/server/bad.py"}
    assert any(v.token == FORBIDDEN_TOKENS[2] for v in violations)


def test_boundary_scanner_flags_product_test_references(tmp_path):
    tests = tmp_path / "editor" / "server" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_bad.py").write_text(f"SCRIPT = {FORBIDDEN_TOKENS[4]!r}\n")

    violations = scan_runtime_boundaries(tmp_path)

    assert violations
    assert {v.path for v in violations} == {"editor/server/tests/test_bad.py"}


def test_boundary_scanner_accepts_clean_product_files(tmp_path):
    runtime = tmp_path / "editor" / "server"
    runtime.mkdir(parents=True)
    (runtime / "stage.py").write_text("SCRIPT = 'product_generation.py'\n")

    assert scan_runtime_boundaries(tmp_path) == []


def test_repository_product_files_have_no_forbidden_references():
    repo_root = Path(__file__).resolve().parents[3]

    violations = scan_runtime_boundaries(repo_root)

    assert violations == []
