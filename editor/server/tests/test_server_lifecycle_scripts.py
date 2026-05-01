"""Story 31 server lifecycle and test taxonomy checks."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def test_stop_editor_script_clears_known_port():
    if shutil.which("lsof") is None:
        pytest.skip("stop_editor.sh uses lsof to find listening processes")
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not _listening(port):
            time.sleep(0.05)
        assert _listening(port)

        result = subprocess.run(
            [str(REPO_ROOT / "scripts" / "stop_editor.sh"), str(port)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, result.stderr
        assert not _listening(port)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_web_dev_and_e2e_scripts_use_repo_lifecycle_scripts():
    dev = (REPO_ROOT / "editor" / "web" / "scripts" / "dev.sh").read_text()
    e2e = (REPO_ROOT / "editor" / "web" / "scripts" / "e2e.sh").read_text()
    teardown = (REPO_ROOT / "editor" / "web" / "scripts" / "teardown_servers.sh").read_text()

    assert "scripts/start_editor.sh" in dev
    assert "scripts/stop_editor.sh" in e2e
    assert "scripts/stop_editor.sh" in teardown


def test_playwright_never_reuses_existing_servers():
    config = (REPO_ROOT / "editor" / "web" / "playwright.config.ts").read_text()

    assert "reuseExistingServer: false" in config
    assert "setup_backend.sh" in config
    assert "timeout: 30_000" in config


def test_package_scripts_separate_fake_backed_and_product_diagnostics():
    package = json.loads((REPO_ROOT / "editor" / "web" / "package.json").read_text())
    scripts = package["scripts"]

    assert scripts["test"] == "bun run test:unit"
    assert "EDITOR_E2E_SUITE=fake-backed" in scripts["test:e2e:fake"]
    assert scripts["test:e2e"] == "bun run test:e2e:fake"
    assert "check_dev_environment.py --mode dev" in scripts["test:e2e:product:diagnose"]


def test_readme_documents_clean_checkout_and_test_taxonomy():
    readme = (REPO_ROOT / "README.md").read_text()

    assert "Clean Checkout Setup" in readme
    assert "scripts/check_dev_environment.py --mode dev" in readme
    assert "test:e2e:fake" in readme
    assert "fake-backed E2E" in readme
    assert "never reuse already-running local servers" in readme
