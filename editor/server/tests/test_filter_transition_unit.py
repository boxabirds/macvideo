"""Story 11 unit tests for filter transition kind and conflict rules."""

from __future__ import annotations

import time

from ..pipeline.transitions import CONFLICT_SCOPES, FilterChangeTransition
from ..regen.runs import RegenScope
from .test_transitions import _insert_scene, _insert_song, test_db


def test_kind_classifier_matrix(test_db):
    fresh_id = _insert_song(test_db, "fresh", filter_val=None, world_brief=None)
    assert FilterChangeTransition(test_db, "fresh", "cyanotype").kind() == "fresh-setup"

    _insert_scene(test_db, fresh_id)
    assert FilterChangeTransition(test_db, "fresh", "watercolour").kind() == "destructive"

    _insert_song(test_db, "same", filter_val="cyanotype", world_brief="brief")
    assert FilterChangeTransition(test_db, "same", "cyanotype").kind() == "noop"

    _insert_song(test_db, "unset", filter_val="cyanotype", world_brief="brief")
    assert FilterChangeTransition(test_db, "unset", None).kind() == "destructive"

    _insert_song(test_db, "recovery", filter_val="cyanotype", world_brief=None)
    assert FilterChangeTransition(test_db, "recovery", "watercolour").kind() == "destructive"


def test_conflict_scope_enumeration_parity():
    literals = set(RegenScope.__args__)  # type: ignore[attr-defined]
    explicitly_excluded = {"scene_keyframe", "scene_clip", "final_video"}
    assert literals - CONFLICT_SCOPES == explicitly_excluded


def test_conflict_reason_for_each_chain_scope(test_db):
    song_id = _insert_song(test_db, "conflicted", filter_val="cyanotype")
    now = time.time()
    for scope in sorted(CONFLICT_SCOPES):
        test_db.execute("DELETE FROM regen_runs")
        test_db.execute(
            "INSERT INTO regen_runs (scope, song_id, status, created_at) VALUES (?, ?, 'running', ?)",
            (scope, song_id, now),
        )
        test_db.commit()
        reason = FilterChangeTransition(test_db, "conflicted", "watercolour").conflict_reason()
        assert reason is not None
        assert "chain already running" in reason


def test_done_or_failed_runs_do_not_conflict(test_db):
    song_id = _insert_song(test_db, "complete", filter_val="cyanotype")
    now = time.time()
    for status in ("done", "failed"):
        test_db.execute("DELETE FROM regen_runs")
        test_db.execute(
            "INSERT INTO regen_runs (scope, song_id, status, created_at) VALUES ('song_filter', ?, ?, ?)",
            (song_id, status, now),
        )
        test_db.commit()
        assert FilterChangeTransition(test_db, "complete", "watercolour").conflict_reason() is None
