"""Persistence layer for regen_runs rows.

Pure CRUD around the table created by store.schema. All regen orchestration
(stories 4, 5, 8, 9, 10) reads and writes runs through these functions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal, Optional

from ..store.schema import RegenStatus


RegenScope = Literal[
    "scene_keyframe", "scene_clip",
    "song_filter", "song_abstraction",
    "stage_transcribe", "stage_world_brief", "stage_storyboard",
    "stage_image_prompts", "stage_keyframes",
    "final_video",
]


@dataclass
class RegenRun:
    id: int
    scope: RegenScope
    song_id: int
    scene_id: Optional[int]
    artefact_kind: Optional[str]
    status: RegenStatus
    quality_mode: Optional[str]
    cost_estimate_usd: Optional[float]
    started_at: Optional[float]
    ended_at: Optional[float]
    error: Optional[str]
    created_at: float


def create_run(
    conn, *, scope: RegenScope, song_id: int,
    scene_id: Optional[int] = None,
    artefact_kind: Optional[str] = None,
    quality_mode: Optional[str] = None,
    cost_estimate_usd: Optional[float] = None,
) -> int:
    now = time.time()
    cur = conn.execute(
        """INSERT INTO regen_runs
           (scope, song_id, scene_id, artefact_kind, status,
            quality_mode, cost_estimate_usd, created_at)
           VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
        (scope, song_id, scene_id, artefact_kind, quality_mode,
         cost_estimate_usd, now),
    )
    return cur.lastrowid


def get_run(conn, run_id: int) -> Optional[RegenRun]:
    row = conn.execute(
        "SELECT * FROM regen_runs WHERE id = ?", (run_id,),
    ).fetchone()
    return _row_to_run(row) if row else None


def list_song_runs(conn, song_id: int, *, active_only: bool = False) -> list[RegenRun]:
    if active_only:
        rows = conn.execute(
            "SELECT * FROM regen_runs WHERE song_id = ? "
            "AND status IN ('pending', 'running') "
            "ORDER BY created_at DESC",
            (song_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM regen_runs WHERE song_id = ? ORDER BY created_at DESC LIMIT 200",
            (song_id,),
        ).fetchall()
    return [_row_to_run(r) for r in rows]


def update_run_status(
    conn, run_id: int, status: RegenStatus, *, error: Optional[str] = None,
) -> None:
    now = time.time()
    if status == "running":
        conn.execute(
            "UPDATE regen_runs SET status = ?, started_at = COALESCE(started_at, ?) WHERE id = ?",
            (status, now, run_id),
        )
    elif status in ("done", "failed", "cancelled"):
        conn.execute(
            "UPDATE regen_runs SET status = ?, ended_at = ?, error = ? WHERE id = ?",
            (status, now, error, run_id),
        )
    else:
        conn.execute(
            "UPDATE regen_runs SET status = ? WHERE id = ?",
            (status, run_id),
        )


def _row_to_run(row) -> RegenRun:
    return RegenRun(
        id=row["id"],
        scope=row["scope"],
        song_id=row["song_id"],
        scene_id=row["scene_id"],
        artefact_kind=row["artefact_kind"],
        status=row["status"],
        quality_mode=row["quality_mode"],
        cost_estimate_usd=row["cost_estimate_usd"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        error=row["error"],
        created_at=row["created_at"],
    )
