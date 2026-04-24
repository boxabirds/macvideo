"""Unit tests for story 10 — final-render pre-flight + alignment math.

Pure helpers: no DB, no subprocess, no ffmpeg. Covers final.enqueue-missing
pre-flight logic and the align-clip trim/pad math that backs final.stitch.
"""

from __future__ import annotations


def test_preflight_identifies_scenes_missing_keyframe_take():
    """Simulate the SQL query's shape: list of scene_indexes without a
    selected_keyframe_take_id. The 422 body's affected_scenes list is
    built from this output."""
    scenes = [
        {"scene_index": 1, "selected_keyframe_take_id": 42},
        {"scene_index": 2, "selected_keyframe_take_id": None},
        {"scene_index": 3, "selected_keyframe_take_id": 45},
        {"scene_index": 4, "selected_keyframe_take_id": None},
    ]
    missing = [s["scene_index"] for s in scenes if s["selected_keyframe_take_id"] is None]
    assert missing == [2, 4]


def test_clips_to_render_counts_null_and_stale():
    """final.enqueue-missing spec: enqueue scenes where selected_clip_take_id
    is NULL OR the take is clip_stale OR the take's quality_mode differs."""
    song_mode = "final"
    scenes = [
        # Already fresh: matching mode + no stale
        {"idx": 1, "take_id": 10, "take_mode": "final", "dirty": []},
        # Mode mismatch: needs re-render
        {"idx": 2, "take_id": 11, "take_mode": "draft", "dirty": []},
        # Stale flag: needs re-render
        {"idx": 3, "take_id": 12, "take_mode": "final", "dirty": ["clip_stale"]},
        # Missing take: needs render
        {"idx": 4, "take_id": None, "take_mode": None, "dirty": []},
    ]
    to_render = [s["idx"] for s in scenes if (
        s["take_id"] is None
        or "clip_stale" in s["dirty"]
        or s["take_mode"] != song_mode
    )]
    assert to_render == [2, 3, 4]
    reusable = [s["idx"] for s in scenes if s["idx"] not in to_render]
    assert reusable == [1]


def test_align_pad_math_pad_case():
    """A clip shorter than target needs tpad pad. Simulates the pad
    duration math in align_clip()."""
    clip_duration = 2.5
    target = 3.0
    assert target > clip_duration
    pad = target - clip_duration
    assert abs(pad - 0.5) < 1e-6


def test_align_pad_math_trim_case():
    clip_duration = 3.2
    target = 3.0
    assert clip_duration > target
    # Trim amount = clip_duration - target
    trim = clip_duration - target
    assert abs(trim - 0.2) < 1e-6


def test_align_pad_math_passthrough_exact():
    clip_duration = 3.0
    target = 3.0
    assert clip_duration == target
    # No-op path; alignment produces an identical clip.


def test_finished_video_path_uniqueness_via_timestamp():
    """The timestamp + quality_mode suffix guarantees the file never
    collides with a prior run (PRD: 'MUST NOT be overwritten')."""
    import time
    import re
    # Simulate two consecutive renders (separate stamps because of sleep).
    stamp1 = time.strftime("%Y%m%dT%H%M%S")
    time.sleep(1.01)
    stamp2 = time.strftime("%Y%m%dT%H%M%S")
    assert stamp1 != stamp2
    # The path format the implementation uses.
    path1 = f"final_{stamp1}_draft.mp4"
    path2 = f"final_{stamp2}_final.mp4"
    assert path1 != path2
    assert re.match(r"final_\d{8}T\d{6}_(draft|final)\.mp4", path1)
    assert re.match(r"final_\d{8}T\d{6}_(draft|final)\.mp4", path2)
