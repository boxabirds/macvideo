"""Unit tests for filter.chain-execute's pure helpers.

The chain's subprocess orchestration is integration-tested (needs TestClient
+ fake scripts). The pure helpers — which fields trigger a chain, what the
chain's scope looks like for a given song — are unit-testable in isolation.
"""

from __future__ import annotations

from editor.server.pipeline.pricing import estimate_filter_change


def test_chain_scope_includes_all_downstream_stages():
    """A filter change must regen world-brief + storyboard + all prompts +
    all keyframes. Test asserts the ChainEstimate's scope flags reflect
    that so the UI renders an accurate preview."""
    est = estimate_filter_change(
        scene_count=10, user_authored_count=0, clip_count=5,
    )
    assert est.will_regen_world_brief is True
    assert est.will_regen_storyboard is True
    assert est.scenes_with_new_prompts == 10
    assert est.keyframes_to_generate == 10
    assert est.clips_marked_stale == 5


def test_chain_scope_user_authored_prompts_bypass_pass_b():
    """Chain-execute PRD clause: 'Replaces every scenes.image_prompt
    EXCEPT where prompt_is_user_authored=true'. The estimator's
    scenes_with_new_prompts must match that exclusion."""
    est = estimate_filter_change(
        scene_count=10, user_authored_count=3, clip_count=5,
    )
    assert est.scenes_with_new_prompts == 7  # 10 - 3 user-authored
    # Keyframes still regen for all scenes because the IMAGE is filter-
    # dependent even when the prompt is preserved.
    assert est.keyframes_to_generate == 10


def test_chain_scope_handles_zero_clips_gracefully():
    """Songs without any rendered clips yet — clips_marked_stale should
    be 0 and the chain still proceeds."""
    est = estimate_filter_change(
        scene_count=10, user_authored_count=0, clip_count=0,
    )
    assert est.clips_marked_stale == 0
    assert est.will_regen_world_brief is True


def test_chain_scope_on_empty_song():
    """Edge: a song with zero scenes still returns sensible bounds
    (covers the PRD 'partial failure summary MUST NOT claim success for
    failed scenes' — degenerate case keyframes_to_generate=0)."""
    est = estimate_filter_change(
        scene_count=0, user_authored_count=0, clip_count=0,
    )
    assert est.scenes_with_new_prompts == 0
    assert est.keyframes_to_generate == 0
    # Just the 2 world-level calls (Pass A + Pass C).
    assert est.gemini_calls == 2
