"""Shared helpers for API handlers: DB dependency, row-to-dict, error models."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

from fastapi import Depends
from pydantic import BaseModel

from .. import config as _cfg
from ..store import connection


def get_db() -> Iterator[object]:
    """FastAPI dependency yielding a per-request SQLite connection.

    Reads `DB_PATH` via the config module at call time (not at import time)
    so tests that monkeypatch env vars + reload config see the new path.
    """
    with connection(_cfg.DB_PATH) as conn:
        yield conn


def scene_asset_paths(row) -> tuple[str | None, str | None, list[str]]:
    """Return (selected_keyframe_path, selected_clip_path, missing_assets)
    for a scene row assumed to be joined with its selected takes."""
    kf_path = row["selected_keyframe_path"] if "selected_keyframe_path" in row.keys() else None
    clip_path = row["selected_clip_path"] if "selected_clip_path" in row.keys() else None
    missing: list[str] = []
    if kf_path and not os.path.isfile(kf_path):
        missing.append("keyframe")
    if clip_path and not os.path.isfile(clip_path):
        missing.append("clip")
    return kf_path, clip_path, missing


def parse_dirty_flags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return [str(x) for x in v] if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


class ErrorDetail(BaseModel):
    code: str
    message: str
    context: dict | None = None
