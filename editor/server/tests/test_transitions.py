"""Unit tests for FilterChangeTransition kind classifier and contract."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from ..pipeline.transitions import FilterChangeTransition


@pytest.fixture
def test_db():
    """In-memory SQLite test DB."""
    db_path = ":memory:"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Minimal schema: songs + scenes for testing kind classifier.
    conn.executescript("""
        CREATE TABLE songs (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            filter TEXT,
            abstraction INTEGER,
            quality_mode TEXT NOT NULL DEFAULT 'draft',
            world_brief TEXT,
            sequence_arc TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE scenes (
            id INTEGER PRIMARY KEY,
            song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
            scene_index INTEGER NOT NULL,
            kind TEXT NOT NULL,
            target_text TEXT NOT NULL,
            start_s REAL NOT NULL,
            end_s REAL NOT NULL,
            target_duration_s REAL NOT NULL,
            num_frames INTEGER NOT NULL,
            lyric_line_idx INTEGER,
            beat TEXT,
            camera_intent TEXT,
            subject_focus TEXT,
            prev_link TEXT,
            next_link TEXT,
            image_prompt TEXT,
            prompt_is_user_authored INTEGER NOT NULL DEFAULT 0,
            selected_keyframe_take_id INTEGER,
            selected_clip_take_id INTEGER,
            selection_pinned INTEGER NOT NULL DEFAULT 0,
            dirty_flags TEXT NOT NULL DEFAULT '[]',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE (song_id, scene_index)
        );

        CREATE TABLE takes (
            id INTEGER PRIMARY KEY,
            scene_id INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
            artefact_kind TEXT NOT NULL CHECK (artefact_kind IN ('keyframe', 'clip')),
            asset_path TEXT NOT NULL,
            prompt_snapshot TEXT,
            seed INTEGER,
            source_run_id INTEGER,
            quality_mode TEXT CHECK (quality_mode IS NULL OR quality_mode IN ('draft', 'final')),
            created_by TEXT NOT NULL DEFAULT 'cli',
            created_at REAL NOT NULL,
            UNIQUE (scene_id, artefact_kind, asset_path)
        );

        CREATE TABLE regen_runs (
            id INTEGER PRIMARY KEY,
            scope TEXT NOT NULL,
            song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
            scene_id INTEGER REFERENCES scenes(id) ON DELETE CASCADE,
            artefact_kind TEXT,
            status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'done', 'failed', 'cancelled')),
            quality_mode TEXT,
            cost_estimate_usd REAL,
            started_at REAL,
            ended_at REAL,
            error TEXT,
            progress_pct INTEGER,
            phase TEXT,
            created_at REAL NOT NULL
        );
    """)

    yield conn
    conn.close()


def _insert_song(conn, slug: str, filter_val=None, world_brief=None, abstraction=None):
    """Helper to insert a test song."""
    now = time.time()
    conn.execute(
        """INSERT INTO songs (slug, filter, abstraction, quality_mode, world_brief, created_at, updated_at)
           VALUES (?, ?, ?, 'draft', ?, ?, ?)""",
        (slug, filter_val, abstraction, world_brief, now, now),
    )
    conn.commit()
    return conn.execute("SELECT id FROM songs WHERE slug = ?", (slug,)).fetchone()["id"]


def _insert_scene(conn, song_id: int, scene_index: int = 0):
    """Helper to insert a test scene."""
    now = time.time()
    conn.execute(
        """INSERT INTO scenes
           (song_id, scene_index, kind, target_text, start_s, end_s, target_duration_s, num_frames, created_at, updated_at)
           VALUES (?, ?, 'dialogue', 'test', 0, 1, 1, 33, ?, ?)""",
        (song_id, scene_index, now, now),
    )
    conn.commit()


class TestFilterChangeTransitionKind:
    """Tests for kind() classification."""

    def test_noop_same_filter(self, test_db):
        """Setting filter to its current value is a noop."""
        song_id = _insert_song(test_db, "test", filter_val="cyanotype")
        transition = FilterChangeTransition(test_db, "test", new_filter="cyanotype")
        assert transition.kind() == "noop"

    def test_fresh_setup_three_conditions(self, test_db):
        """Fresh-setup: filter=None, world_brief=None, no scenes, setting new filter."""
        song_id = _insert_song(test_db, "fresh", filter_val=None, world_brief=None)
        transition = FilterChangeTransition(test_db, "fresh", new_filter="cyanotype")
        assert transition.kind() == "fresh-setup"

    def test_fresh_setup_requires_all_three(self, test_db):
        """If any condition is false, it's not fresh-setup."""
        # Has world_brief → not fresh-setup
        song_id = _insert_song(test_db, "has_brief", filter_val=None, world_brief="narrator")
        transition = FilterChangeTransition(test_db, "has_brief", new_filter="cyanotype")
        assert transition.kind() == "destructive"

    def test_fresh_setup_with_existing_scene_is_destructive(self, test_db):
        """If filter=None but scenes exist (from transcription), it's destructive."""
        song_id = _insert_song(test_db, "transcribed", filter_val=None, world_brief=None)
        _insert_scene(test_db, song_id)
        transition = FilterChangeTransition(test_db, "transcribed", new_filter="cyanotype")
        assert transition.kind() == "destructive"

    def test_destructive_filter_change_on_existing_song(self, test_db):
        """Changing filter on a song with state (filter set, has world_brief, has scenes)."""
        song_id = _insert_song(test_db, "existing", filter_val="oil impasto", world_brief="narrator")
        _insert_scene(test_db, song_id)
        transition = FilterChangeTransition(test_db, "existing", new_filter="cyanotype")
        assert transition.kind() == "destructive"


class TestFilterChangeTransitionPreview:
    """Tests for preview() structure and estimation."""

    def test_preview_has_required_fields(self, test_db):
        """preview() returns the dict with from/to/scope/estimate/would_conflict_with."""
        song_id = _insert_song(test_db, "test", filter_val="oil impasto", world_brief="narrator")
        _insert_scene(test_db, song_id)

        transition = FilterChangeTransition(test_db, "test", new_filter="cyanotype")
        preview = transition.preview()

        assert "from" in preview
        assert "to" in preview
        assert "scope" in preview
        assert "estimate" in preview
        assert "would_conflict_with" in preview

    def test_preview_from_to_structure(self, test_db):
        """from/to have filter and abstraction."""
        song_id = _insert_song(test_db, "test", filter_val="oil impasto", abstraction=25)
        transition = FilterChangeTransition(test_db, "test", new_filter="cyanotype")
        preview = transition.preview()

        assert preview["from"]["filter"] == "oil impasto"
        assert preview["from"]["abstraction"] == 25
        assert preview["to"]["filter"] == "cyanotype"
        assert preview["to"]["abstraction"] == 25

    def test_preview_scope_on_fresh_song(self, test_db):
        """Fresh song: no existing clips, so clips_marked_stale = 0."""
        song_id = _insert_song(test_db, "fresh", filter_val=None, world_brief=None)
        transition = FilterChangeTransition(test_db, "fresh", new_filter="cyanotype")
        preview = transition.preview()

        assert preview["scope"]["clips_marked_stale"] == 0
        assert preview["scope"]["will_regen_world_brief"] is True
        assert preview["scope"]["will_regen_storyboard"] is True

    def test_preview_clips_marked_stale_counts_with_clip_take(self, test_db):
        """Clips marked stale = number of scenes with selected_clip_take_id."""
        song_id = _insert_song(test_db, "test", filter_val="oil impasto", world_brief="narrator")

        now = time.time()
        conn = test_db
        # Insert scene and a clip take
        cursor = conn.execute(
            """INSERT INTO scenes
               (song_id, scene_index, kind, target_text, start_s, end_s, target_duration_s, num_frames, created_at, updated_at)
               VALUES (?, 0, 'dialogue', 'test', 0, 1, 1, 33, ?, ?)""",
            (song_id, now, now),
        )
        scene_id = cursor.lastrowid
        cursor = conn.execute(
            """INSERT INTO takes (scene_id, artefact_kind, asset_path, created_by, created_at)
               VALUES (?, 'clip', '/path/clip.mp4', 'editor', ?)""",
            (scene_id, now),
        )
        take_id = cursor.lastrowid
        conn.execute(
            "UPDATE scenes SET selected_clip_take_id = ? WHERE id = ?",
            (take_id, scene_id),
        )
        conn.commit()

        transition = FilterChangeTransition(test_db, "test", new_filter="cyanotype")
        preview = transition.preview()

        assert preview["scope"]["clips_marked_stale"] == 1

    def test_preview_conflict_none_when_no_active_regen(self, test_db):
        """would_conflict_with is None if no pending/running regen_runs."""
        song_id = _insert_song(test_db, "test", filter_val="oil impasto")
        transition = FilterChangeTransition(test_db, "test", new_filter="cyanotype")
        preview = transition.preview()

        assert preview["would_conflict_with"] is None

    def test_preview_conflict_detected_on_pending_run(self, test_db):
        """would_conflict_with is set if there's a pending/running regen_run."""
        song_id = _insert_song(test_db, "test", filter_val="oil impasto")
        now = time.time()
        test_db.execute(
            """INSERT INTO regen_runs
               (scope, song_id, status, created_at)
               VALUES ('song_filter', ?, 'running', ?)""",
            (song_id, now),
        )
        test_db.commit()

        transition = FilterChangeTransition(test_db, "test", new_filter="cyanotype")
        preview = transition.preview()

        assert preview["would_conflict_with"] is not None
        assert "run_id" in preview["would_conflict_with"]
        assert "reason" in preview["would_conflict_with"]


class TestFilterChangeTransitionConflictReason:
    """Tests for conflict_reason()."""

    def test_conflict_reason_none_when_no_conflict(self, test_db):
        """conflict_reason() is None when no pending/running runs."""
        song_id = _insert_song(test_db, "test", filter_val="oil impasto")
        transition = FilterChangeTransition(test_db, "test", new_filter="cyanotype")
        assert transition.conflict_reason() is None

    def test_conflict_reason_when_regen_running(self, test_db):
        """conflict_reason() returns a message when a run is active."""
        song_id = _insert_song(test_db, "test", filter_val="oil impasto")
        now = time.time()
        test_db.execute(
            """INSERT INTO regen_runs
               (scope, song_id, status, created_at)
               VALUES ('song_filter', ?, 'pending', ?)""",
            (song_id, now),
        )
        test_db.commit()

        transition = FilterChangeTransition(test_db, "test", new_filter="cyanotype")
        reason = transition.conflict_reason()
        assert reason is not None
        assert "already running" in reason.lower() or "conflict" in reason.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
