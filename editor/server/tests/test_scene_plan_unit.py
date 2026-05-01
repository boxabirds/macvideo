"""Story 27 saved scene and timed correction rules."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from editor.server.api.transcript import _apply_correction, _fetch_scene, _response
from editor.server.store.scene_plan import load_song_scene_plan
from editor.server.store.schema import init_db


def _db(tmp_path: Path):
    dbp = tmp_path / "scene-plan.db"
    init_db(dbp)
    conn = sqlite3.connect(str(dbp), isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _song(conn, slug="song"):
    now = time.time()
    cur = conn.execute(
        """
        INSERT INTO songs (
            slug, audio_path, duration_s, size_bytes, filter, abstraction,
            quality_mode, created_at, updated_at
        ) VALUES (?, '/song.wav', 4, 100, 'charcoal', 0, 'draft', ?, ?)
        """,
        (slug, now, now),
    )
    return cur.lastrowid


def _scene(conn, song_id, *, idx=1, text="first middle last", start=10.0, end=16.0):
    now = time.time()
    conn.execute(
        """
        INSERT INTO scenes (
            song_id, scene_index, kind, target_text, start_s, end_s,
            target_duration_s, num_frames, created_at, updated_at
        ) VALUES (?, ?, 'lyric', ?, ?, ?, ?, 24, ?, ?)
        """,
        (song_id, idx, text, start, end, end - start, now, now),
    )


def test_scene_plan_empty_uses_saved_records_without_file_lookup(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)

    plan = load_song_scene_plan(conn, song_id)

    assert plan.empty is True
    assert plan.to_legacy_shots() == {"shots": []}


def test_scene_plan_reads_saved_scene_text_and_timing(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)
    _scene(conn, song_id, text="saved text", start=1.5, end=3.0)

    plan = load_song_scene_plan(conn, song_id)

    assert plan.empty is False
    assert plan.scenes[0].target_text == "saved text"
    assert plan.scenes[0].start_s == 1.5
    assert plan.to_legacy_shots()["shots"][0]["target_text"] == "saved text"


def test_one_word_correction_preserves_first_word_timing(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)
    _scene(conn, song_id)
    scene = _fetch_scene(conn, "song", 1)
    before = _response(conn, scene).words

    _apply_correction(conn, scene=scene, start_idx=0, end_idx=0, text="opening")
    after = _response(conn, scene).words

    assert after[0].text == "opening"
    assert after[0].start_s == before[0].start_s
    assert after[0].end_s == before[0].end_s


def test_last_word_correction_preserves_last_word_timing(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)
    _scene(conn, song_id)
    scene = _fetch_scene(conn, "song", 1)
    before = _response(conn, scene).words

    _apply_correction(conn, scene=scene, start_idx=2, end_idx=2, text="closing")
    after = _response(conn, scene).words

    assert after[-1].text == "closing"
    assert after[-1].start_s == before[-1].start_s
    assert after[-1].end_s == before[-1].end_s


def test_multi_word_correction_spans_original_interval(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)
    _scene(conn, song_id)
    scene = _fetch_scene(conn, "song", 1)
    before = _response(conn, scene).words

    _apply_correction(conn, scene=scene, start_idx=1, end_idx=2, text="middle ending phrase")
    after = _response(conn, scene).words

    assert [w.text for w in after] == ["first", "middle", "ending", "phrase"]
    assert after[1].start_s == before[1].start_s
    assert after[-1].end_s == before[2].end_s


def test_invalid_selection_and_empty_replacement_are_typed_failures(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)
    _scene(conn, song_id)
    scene = _fetch_scene(conn, "song", 1)
    _response(conn, scene)

    with pytest.raises(Exception) as invalid:
        _apply_correction(conn, scene=scene, start_idx=3, end_idx=9, text="nope")
    assert invalid.value.detail["code"] == "invalid_word_selection"

    with pytest.raises(Exception) as empty:
        _apply_correction(conn, scene=scene, start_idx=0, end_idx=0, text="")
    assert empty.value.detail["code"] == "empty_correction"
