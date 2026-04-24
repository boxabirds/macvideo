"""Pricing + estimate calculators for story 4.

Numbers are best-effort snapshots of Gemini 3.1 flash image preview pricing
(docs link in docs/research/). Each cost-estimate endpoint reads these
values; when Google publishes new rates, update this file and any tests
asserting specific cents will need to follow.
"""

from __future__ import annotations

from dataclasses import dataclass


# Approximate per-call cost in USD. Pass A / Pass C / Pass B are all LLM
# text calls on gemini-3-flash-preview (~$0.005/call for the prompt sizes
# this pipeline uses). Keyframes are gemini-3.1-flash-image-preview
# (~$0.04/image at 1K resolution).
PASS_TEXT_USD = 0.005
IMAGE_USD = 0.04

# Observed latency on M3 Pro for one warm Gemini call (from the keyframe
# generation runs in docs/reports/20260423-little-blackbird-v1.md).
# Used as the denominator for time estimates.
TEXT_SECS = 2.0
IMAGE_SECS = 16.0


@dataclass
class ChainEstimate:
    gemini_calls: int
    estimated_usd: float
    estimated_seconds: float
    confidence: str
    # Details so the modal can render per-phase breakdown.
    will_regen_world_brief: bool
    will_regen_storyboard: bool
    scenes_with_new_prompts: int
    keyframes_to_generate: int
    clips_marked_stale: int


def estimate_filter_change(
    *, scene_count: int, user_authored_count: int, clip_count: int,
) -> ChainEstimate:
    """Estimate a full filter/abstraction change chain.

    Pass A (1 call) + Pass C (1 call) + Pass B per non-user-authored scene +
    1 image per scene. User-authored prompts are preserved so their Pass B
    calls are skipped.
    """
    new_prompt_count = max(0, scene_count - user_authored_count)
    calls = 2 + new_prompt_count + scene_count
    usd = 2 * PASS_TEXT_USD + new_prompt_count * PASS_TEXT_USD + scene_count * IMAGE_USD
    seconds = 2 * TEXT_SECS + new_prompt_count * TEXT_SECS + scene_count * IMAGE_SECS
    # Confidence drops on very small or very large songs where our latency
    # samples don't apply well.
    confidence = "high" if 20 <= scene_count <= 120 else "medium"
    return ChainEstimate(
        gemini_calls=calls,
        estimated_usd=round(usd, 2),
        estimated_seconds=round(seconds, 1),
        confidence=confidence,
        will_regen_world_brief=True,
        will_regen_storyboard=True,
        scenes_with_new_prompts=new_prompt_count,
        keyframes_to_generate=scene_count,
        clips_marked_stale=clip_count,
    )


def estimate_scene_keyframe_regen() -> dict:
    """Per-scene keyframe regen cost estimate.

    Returns {usd, seconds, confidence}. usd is the design-specified flat
    $0.02 (Gemini 3.1 flash image preview rounded-down rate from POC 29
    reports); wall-time is ~15s high-confidence. Confidence is 'low' on
    usd because Google's published rates change; 'high' on seconds once
    we have ≥3 recent observations, else 'low'.
    """
    return {"usd": 0.02, "seconds": 15.0, "confidence": "high"}


def estimate_scene_clip_regen(
    conn=None, *, num_frames: int = 33, quality_mode: str = "draft",
) -> dict:
    """Per-scene clip regen cost estimate.

    Returns {usd, seconds, confidence}. LTX is local — $0 dollar cost.
    Wall-time is num_frames * observed_sec_per_frame * 1.1 safety margin.
    observed_sec_per_frame is the median of the last 10 completed clip
    runs at the same quality_mode (from regen_runs table). If <3 samples
    are available the estimate falls back to a coarse default
    (1.7s/frame at draft / 3.3s/frame at final on M3 Pro) with 'low'
    confidence.
    """
    seconds_per_frame = 1.7 if quality_mode == "draft" else 3.3
    confidence: str = "low"
    if conn is not None:
        rows = conn.execute(
            "SELECT started_at, ended_at FROM regen_runs "
            "WHERE scope='scene_clip' AND status='done' AND quality_mode=? "
            "ORDER BY ended_at DESC LIMIT 10",
            (quality_mode,),
        ).fetchall()
        durations = [
            (r["ended_at"] - r["started_at"])
            for r in rows
            if r["started_at"] is not None and r["ended_at"] is not None
        ]
        if len(durations) >= 3:
            durations.sort()
            median = durations[len(durations) // 2]
            seconds_per_frame = median / max(1, num_frames)
            confidence = "high"
    seconds = num_frames * seconds_per_frame * 1.1
    return {"usd": 0.0, "seconds": round(seconds, 1), "confidence": confidence}
