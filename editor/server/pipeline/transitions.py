"""Song state transitions: filter/abstraction changes with kind classification.

Consolidates the filter-change contract (preview, apply, conflict detection) into
a single source of truth, ensuring preview_change endpoint and PATCH handler stay
in sync as the song-change ruleset evolves.

Kind classifier:
- fresh-setup: initial filter pick on a fresh song (filter=None, world_brief=None,
  no scenes yet). UI renders friendly "Set filter" setup modal instead of destructive
  "Confirm change" modal.
- destructive: filter change on a song with existing state (has scenes, or has
  world_brief). Triggers full chain: Pass A + C + image prompts + keyframes. Marks
  existing clips stale.
- noop: setting filter to its current value. No-op at both preview and apply.
"""

from __future__ import annotations

import json
import time
from typing import Literal

from .pricing import estimate_filter_change


class FilterChangeTransition:
    """Stateless model of a proposed filter change."""

    def __init__(self, conn, slug: str, new_filter: str) -> None:
        self.conn = conn
        self.slug = slug
        self.new_filter = new_filter

        # Fetch song row: filter, abstraction, world_brief, and scene count.
        song = self.conn.execute(
            "SELECT id, filter, abstraction, world_brief FROM songs WHERE slug = ?",
            (slug,),
        ).fetchone()
        if song is None:
            raise ValueError(f"Song '{slug}' not found")

        self.song_id = song["id"]
        self.current_filter = song["filter"]
        self.current_abstraction = song["abstraction"]
        self.current_world_brief = song["world_brief"]

        scene_count = self.conn.execute(
            "SELECT COUNT(*) FROM scenes WHERE song_id = ?", (self.song_id,)
        ).fetchone()[0]
        self.scene_count = scene_count

    def kind(self) -> Literal["fresh-setup", "destructive", "noop"]:
        """Classify the type of transition."""
        # noop: filter is already the target value.
        if self.new_filter == self.current_filter:
            return "noop"

        # fresh-setup: filter is None, world_brief is None, no scenes yet.
        # This is the initial filter pick that kicks off the pipeline.
        is_fresh = (
            self.current_filter is None
            and self.current_world_brief is None
            and self.scene_count == 0
        )
        if is_fresh:
            return "fresh-setup"

        # destructive: any other filter change.
        return "destructive"

    def conflict_reason(self) -> str | None:
        """Check if a regen run is pending/running for this song.

        Returns a human-readable reason string if there's a conflict, None otherwise.
        """
        active = self.conn.execute(
            """SELECT id FROM regen_runs
               WHERE song_id = ? AND status IN ('pending', 'running')
               LIMIT 1""",
            (self.song_id,),
        ).fetchone()

        if active:
            return "a chain is already running for this song"
        return None

    def preview(self) -> dict:
        """Compute the preview dict for the UI confirmation modal.

        Returns the same structure as preview_change endpoint:
        {
            "from": {"filter": ..., "abstraction": ...},
            "to": {"filter": ..., "abstraction": ...},
            "scope": {...},
            "estimate": {...},
            "would_conflict_with": {...} or None
        }
        """
        # Fetch counts for the estimate.
        user_authored = self.conn.execute(
            "SELECT COUNT(*) FROM scenes WHERE song_id = ? AND prompt_is_user_authored = 1",
            (self.song_id,),
        ).fetchone()[0]
        clip_count = self.conn.execute(
            "SELECT COUNT(*) FROM scenes WHERE song_id = ? AND selected_clip_take_id IS NOT NULL",
            (self.song_id,),
        ).fetchone()[0]

        # Compute estimate using pricing module.
        est = estimate_filter_change(
            scene_count=self.scene_count,
            user_authored_count=user_authored,
            clip_count=clip_count,
        )

        # Check for conflicts.
        conflict_row = self.conn.execute(
            """SELECT id FROM regen_runs
               WHERE song_id = ? AND status IN ('pending', 'running')
               LIMIT 1""",
            (self.song_id,),
        ).fetchone()
        would_conflict = (
            {
                "run_id": conflict_row["id"],
                "reason": "a chain is already running for this song",
            }
            if conflict_row
            else None
        )

        return {
            "from": {"filter": self.current_filter, "abstraction": self.current_abstraction},
            "to": {"filter": self.new_filter, "abstraction": self.current_abstraction},
            "scope": {
                "will_regen_world_brief": est.will_regen_world_brief,
                "will_regen_storyboard": est.will_regen_storyboard,
                "scenes_with_new_prompts": est.scenes_with_new_prompts,
                "keyframes_to_generate": est.keyframes_to_generate,
                "clips_marked_stale": est.clips_marked_stale,
                "clips_deleted": 0,
            },
            "estimate": {
                "gemini_calls": est.gemini_calls,
                "estimated_usd": est.estimated_usd,
                "estimated_seconds": est.estimated_seconds,
                "confidence": est.confidence,
            },
            "would_conflict_with": would_conflict,
        }
