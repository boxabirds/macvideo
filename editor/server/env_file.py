"""Project-local .env loading for development runtime configuration."""

from __future__ import annotations

import os
from pathlib import Path


def load_project_env(repo_root: Path, *, override: bool = False) -> None:
    """Load KEY=VALUE pairs from repo_root/.env into os.environ.

    This intentionally keeps parsing small and dependency-free. Existing
    process environment wins by default so CI, test harnesses, and command-line
    scoped overrides remain authoritative.
    """
    env_path = repo_root / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or (not override and key in os.environ):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
