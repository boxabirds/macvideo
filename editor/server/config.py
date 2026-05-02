"""Runtime configuration for the editor server.

All paths are resolved from the repo root so the editor can be launched from
anywhere. Override via environment variables for tests.
"""

from __future__ import annotations

import os
from pathlib import Path

from .env_file import load_project_env


REPO_ROOT = Path(os.environ.get("MACVIDEO_REPO_ROOT",
                                Path(__file__).resolve().parents[2]))
EDITOR_ROOT = REPO_ROOT / "editor"

load_project_env(REPO_ROOT)

DB_PATH = Path(os.environ.get("EDITOR_DB_PATH",
                              EDITOR_ROOT / "data" / "editor.db"))

MUSIC_DIR = Path(os.environ.get("EDITOR_MUSIC_DIR", REPO_ROOT / "music"))
OUTPUTS_DIR = Path(os.environ.get("EDITOR_OUTPUTS_DIR",
                                  EDITOR_ROOT / "data" / "outputs"))
