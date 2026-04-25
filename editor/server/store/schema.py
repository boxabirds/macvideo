"""Schema + connection factory for the editor's SQLite store.

Tables:
    songs            one per .wav in music/
    scenes           one per shot, FK to song
    takes            keyframe or clip files, FK to scene
    regen_runs       in-flight and past regenerations
    finished_videos  one row per completed final-video render (story 10)

Conventions:
    - FK enforced via PRAGMA foreign_keys = ON
    - created_at / updated_at are Unix seconds (REAL)
    - Enum fields are stored as TEXT with CHECK constraints mirroring the Python enums
    - dirty_flags stored as a TEXT column holding a JSON array
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Iterator


class ArtefactKind(str, Enum):
    keyframe = "keyframe"
    clip = "clip"


class RegenStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class DirtyFlag(str, Enum):
    keyframe_stale = "keyframe_stale"
    clip_stale = "clip_stale"


class QualityMode(str, Enum):
    draft = "draft"
    final = "final"


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS songs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    slug                TEXT NOT NULL UNIQUE,
    audio_path          TEXT NOT NULL,
    lyrics_path         TEXT,
    duration_s          REAL,
    size_bytes          INTEGER,
    filter              TEXT,
    abstraction         INTEGER,
    quality_mode        TEXT NOT NULL DEFAULT 'draft'
                            CHECK (quality_mode IN ('draft', 'final')),
    world_brief         TEXT,
    sequence_arc        TEXT,
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS scenes (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id                     INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    scene_index                 INTEGER NOT NULL,
    kind                        TEXT NOT NULL,
    target_text                 TEXT NOT NULL,
    start_s                     REAL NOT NULL,
    end_s                       REAL NOT NULL,
    target_duration_s           REAL NOT NULL,
    num_frames                  INTEGER NOT NULL,
    lyric_line_idx              INTEGER,
    beat                        TEXT,
    camera_intent               TEXT,
    subject_focus               TEXT,
    prev_link                   TEXT,
    next_link                   TEXT,
    image_prompt                TEXT,
    prompt_is_user_authored     INTEGER NOT NULL DEFAULT 0,
    selected_keyframe_take_id   INTEGER REFERENCES takes(id) ON DELETE SET NULL,
    selected_clip_take_id       INTEGER REFERENCES takes(id) ON DELETE SET NULL,
    selection_pinned            INTEGER NOT NULL DEFAULT 0,
    dirty_flags                 TEXT NOT NULL DEFAULT '[]',
    created_at                  REAL NOT NULL,
    updated_at                  REAL NOT NULL,
    UNIQUE (song_id, scene_index)
);

CREATE TABLE IF NOT EXISTS takes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    scene_id            INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    artefact_kind       TEXT NOT NULL
                            CHECK (artefact_kind IN ('keyframe', 'clip')),
    asset_path          TEXT NOT NULL,
    prompt_snapshot     TEXT,
    seed                INTEGER,
    source_run_id       INTEGER,
    quality_mode        TEXT
                            CHECK (quality_mode IS NULL OR quality_mode IN ('draft', 'final')),
    created_by          TEXT NOT NULL DEFAULT 'cli'
                            CHECK (created_by IN ('cli', 'editor')),
    created_at          REAL NOT NULL,
    UNIQUE (scene_id, artefact_kind, asset_path)
);

CREATE TABLE IF NOT EXISTS regen_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    scope               TEXT NOT NULL
                            CHECK (scope IN ('scene_keyframe', 'scene_clip',
                                             'song_filter', 'song_abstraction',
                                             'stage_transcribe', 'stage_world_brief',
                                             'stage_storyboard', 'stage_image_prompts',
                                             'stage_keyframes', 'final_video')),
    song_id             INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    scene_id            INTEGER REFERENCES scenes(id) ON DELETE CASCADE,
    artefact_kind       TEXT
                            CHECK (artefact_kind IS NULL OR artefact_kind IN ('keyframe', 'clip')),
    status              TEXT NOT NULL
                            CHECK (status IN ('pending', 'running', 'done', 'failed', 'cancelled')),
    quality_mode        TEXT
                            CHECK (quality_mode IS NULL OR quality_mode IN ('draft', 'final')),
    cost_estimate_usd   REAL,
    started_at          REAL,
    ended_at            REAL,
    error               TEXT,
    progress_pct        INTEGER,
    created_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS finished_videos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id             INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    file_path           TEXT NOT NULL,
    quality_mode        TEXT NOT NULL
                            CHECK (quality_mode IN ('draft', 'final')),
    scene_count         INTEGER NOT NULL,
    gap_count           INTEGER NOT NULL DEFAULT 0,
    final_run_id        INTEGER REFERENCES regen_runs(id) ON DELETE SET NULL,
    created_at          REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scenes_song_idx
    ON scenes (song_id, scene_index);

CREATE INDEX IF NOT EXISTS idx_takes_scene_kind_created
    ON takes (scene_id, artefact_kind, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_regen_runs_status_started
    ON regen_runs (status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_regen_runs_song_scope_status
    ON regen_runs (song_id, scope, status);

CREATE INDEX IF NOT EXISTS idx_finished_videos_song_created
    ON finished_videos (song_id, created_at DESC);
"""


def init_db(path: Path) -> None:
    """Apply DDL idempotently. Safe to call at every server startup.

    Also switches the DB into WAL mode so readers and writers can coexist —
    the default rollback-journal mode locks the whole DB for any writer,
    which blocks the FastAPI request thread whenever a background import or
    regen is running.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=30) as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.execute("PRAGMA synchronous = NORMAL")
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA busy_timeout = 30000")
        c.executescript(_SCHEMA_SQL)
        # Idempotent migration for older DBs that predate progress_pct.
        # PRAGMA table_info returns one row per column; check before ALTER.
        cols = {row[1] for row in c.execute("PRAGMA table_info(regen_runs)").fetchall()}
        if "progress_pct" not in cols:
            c.execute("ALTER TABLE regen_runs ADD COLUMN progress_pct INTEGER")
        c.commit()


@contextmanager
def connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a connection with FK enforcement + Row factory + 30s busy timeout.

    `check_same_thread=False` is required because FastAPI runs sync
    dependencies in a threadpool; the yielded connection can end up being
    used on the main async event-loop thread after the dep returns. WAL
    mode + busy_timeout make this safe.
    """
    conn = sqlite3.connect(path, isolation_level=None, timeout=30,
                           check_same_thread=False)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()
