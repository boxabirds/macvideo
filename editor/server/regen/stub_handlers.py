"""Placeholder handlers for regen stages.

The full stage runners that shell out to `gen_keyframes.py` /
`render_clips.py` are out of scope for this first implementation pass; these
stubs exist so the API surface (POST /api/.../scenes/.../takes etc.) is
exercisable end-to-end. Each stub sleeps briefly, creates a take pointing at
the scene's first existing asset (or a placeholder path), and returns.

This means the editor can run its full UI loop now; swapping in the real
subprocess handlers is a localised backend change later.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from .runs import RegenRun
from ..store import connection


async def stub_keyframe_handler(run: RegenRun, *, db_path: Path) -> None:
    """Create a new keyframe take pointing to a placeholder path so the UI
    can see a take appear. No Gemini call; no real image."""
    await asyncio.sleep(0.3)
    with connection(db_path) as conn:
        scene_row = conn.execute(
            "SELECT scene_index, image_prompt FROM scenes WHERE id = ?", (run.scene_id,),
        ).fetchone()
        if not scene_row:
            return
        # Use the existing first keyframe take as the asset path if there is one
        prev = conn.execute(
            "SELECT asset_path FROM takes WHERE scene_id = ? AND artefact_kind = 'keyframe' "
            "ORDER BY created_at DESC LIMIT 1",
            (run.scene_id,),
        ).fetchone()
        base = prev["asset_path"] if prev else f"(stub) scene {scene_row['scene_index']}"
        asset_path = f"{base}#run{run.id}"
        conn.execute(
            "INSERT INTO takes (scene_id, artefact_kind, asset_path, "
            "prompt_snapshot, seed, source_run_id, quality_mode, created_by, created_at) "
            "VALUES (?, 'keyframe', ?, ?, NULL, ?, NULL, 'editor', ?)",
            (run.scene_id, asset_path, scene_row["image_prompt"], run.id, time.time()),
        )


async def stub_clip_handler(run: RegenRun, *, db_path: Path) -> None:
    """Stub clip handler — same shape as keyframe stub but for clips."""
    await asyncio.sleep(0.5)
    with connection(db_path) as conn:
        scene_row = conn.execute(
            "SELECT scene_index FROM scenes WHERE id = ?", (run.scene_id,),
        ).fetchone()
        if not scene_row:
            return
        prev = conn.execute(
            "SELECT asset_path FROM takes WHERE scene_id = ? AND artefact_kind = 'clip' "
            "ORDER BY created_at DESC LIMIT 1",
            (run.scene_id,),
        ).fetchone()
        base = prev["asset_path"] if prev else f"(stub) clip {scene_row['scene_index']}"
        asset_path = f"{base}#run{run.id}"
        conn.execute(
            "INSERT INTO takes (scene_id, artefact_kind, asset_path, "
            "prompt_snapshot, seed, source_run_id, quality_mode, created_by, created_at) "
            "VALUES (?, 'clip', ?, NULL, NULL, ?, ?, 'editor', ?)",
            (run.scene_id, asset_path, run.id, run.quality_mode, time.time()),
        )
