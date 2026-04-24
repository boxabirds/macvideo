"""Unit tests for the regen cost-estimate logic (story 5).

Covers:
- estimate_scene_keyframe_regen returns the fixed $0.02 / 15s design values.
- estimate_scene_clip_regen falls back to coarse defaults when <3 samples.
- estimate_scene_clip_regen uses median-of-last-10 when enough samples exist.
- estimate_filter_change (story 4) scales calls correctly with user-authored
  count and clip count.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from editor.server.pipeline.pricing import (
    estimate_filter_change,
    estimate_scene_clip_regen,
    estimate_scene_keyframe_regen,
)
from editor.server.store.schema import init_db


def test_keyframe_regen_returns_fixed_rate():
    est = estimate_scene_keyframe_regen()
    assert est == {"usd": 0.02, "seconds": 15.0, "confidence": "high"}


def test_clip_regen_falls_back_to_defaults_without_history():
    est = estimate_scene_clip_regen(num_frames=33, quality_mode="draft")
    assert est["usd"] == 0.0
    # 33 frames * 1.7 s/frame * 1.1 safety margin ≈ 61.7
    assert 55 <= est["seconds"] <= 65
    assert est["confidence"] == "low"


def test_clip_regen_final_mode_uses_higher_default():
    est = estimate_scene_clip_regen(num_frames=33, quality_mode="final")
    # 33 * 3.3 * 1.1 ≈ 120
    assert est["seconds"] > 100
    assert est["confidence"] == "low"


def test_clip_regen_uses_median_when_enough_samples_exist():
    with tempfile.TemporaryDirectory() as td:
        dbp = Path(td) / "u.db"
        init_db(dbp)
        conn = sqlite3.connect(str(dbp), isolation_level=None)
        conn.row_factory = sqlite3.Row
        # Seed the song + 5 completed draft clip runs with varying durations.
        conn.execute("""
            INSERT INTO songs (slug, audio_path, duration_s, size_bytes,
                               quality_mode, created_at, updated_at)
            VALUES ('s', '/x', 5, 100, 'draft', 0, 0)
        """)
        song_id = conn.execute("SELECT id FROM songs WHERE slug='s'").fetchone()["id"]
        for started, ended in [(0, 50), (0, 55), (0, 60), (0, 70), (0, 80)]:
            conn.execute("""
                INSERT INTO regen_runs (scope, song_id, status, started_at,
                                        ended_at, quality_mode, created_at)
                VALUES ('scene_clip', ?, 'done', ?, ?, 'draft', 0)
            """, (song_id, started, ended))

        est = estimate_scene_clip_regen(conn, num_frames=30, quality_mode="draft")
        # Median of 5 is 60, /30 = 2s per frame, *30*1.1 = 66
        assert 60 <= est["seconds"] <= 72
        assert est["confidence"] == "high"


def test_filter_change_estimate_scales_with_scene_count():
    est = estimate_filter_change(scene_count=69, user_authored_count=0, clip_count=65)
    # 1 Pass A + 1 Pass C + 69 Pass B + 69 keyframes = 140
    assert est.gemini_calls == 140
    assert est.keyframes_to_generate == 69
    assert est.clips_marked_stale == 65


def test_filter_change_estimate_skips_user_authored_pass_b():
    est = estimate_filter_change(scene_count=69, user_authored_count=10, clip_count=65)
    # Pass B only runs for 59 non-user-authored scenes; images still run for all 69
    assert est.scenes_with_new_prompts == 59
    assert est.gemini_calls == 2 + 59 + 69


def test_filter_change_confidence_drops_outside_normal_range():
    tiny = estimate_filter_change(scene_count=3, user_authored_count=0, clip_count=0)
    assert tiny.confidence in ("low", "medium")
    huge = estimate_filter_change(scene_count=500, user_authored_count=0, clip_count=0)
    assert huge.confidence in ("low", "medium")
    normal = estimate_filter_change(scene_count=70, user_authored_count=0, clip_count=0)
    assert normal.confidence == "high"
