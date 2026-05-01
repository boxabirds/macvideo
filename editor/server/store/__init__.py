"""SQLite-backed authoritative store for the storyboard editor.

Exposes:
    - init_db(path): idempotent DDL application. Call once at server startup.
    - connection(path): context manager yielding a configured sqlite3.Connection.
    - Enums: ArtefactKind, RegenStatus, DirtyFlag.
"""

from .schema import (
    ArtefactKind,
    DirtyFlag,
    RegenStatus,
    QualityMode,
    connection,
    init_db,
)
from .scene_plan import ScenePlan, ScenePlanRow, load_song_scene_plan

__all__ = [
    "ArtefactKind",
    "DirtyFlag",
    "RegenStatus",
    "QualityMode",
    "connection",
    "init_db",
    "ScenePlan",
    "ScenePlanRow",
    "load_song_scene_plan",
]
