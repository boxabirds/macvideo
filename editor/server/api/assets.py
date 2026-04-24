"""Static asset endpoints with HTTP Range support.

Serves files from music/ and pocs/29-full-song/outputs/ under /assets/*
prefixes. The range-aware responder is the critical fix from the preview.html
saga — without it audio seeking silently breaks.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from .. import config as _cfg
from ..range_static import serve_file_with_ranges


router = APIRouter()


def _resolve_safely(root: Path, relative: str) -> Path:
    """Prevent path traversal: the resolved path must live inside `root`."""
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="path escapes allowed root")
    return candidate


@router.get("/assets/music/{path:path}")
def music_asset(path: str, request: Request):
    return serve_file_with_ranges(request, _resolve_safely(_cfg.MUSIC_DIR, path))


@router.get("/assets/outputs/{path:path}")
def output_asset(path: str, request: Request):
    return serve_file_with_ranges(request, _resolve_safely(_cfg.OUTPUTS_DIR, path))
