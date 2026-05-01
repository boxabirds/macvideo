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


class NotFoundError(ValueError):
    """Raised when a requested song slug does not exist."""


class ConflictError(RuntimeError):
    """Raised when a conflicting regen run is already active."""


CONFLICT_SCOPES = {
    "song_filter",
    "song_abstraction",
    "stage_world_brief",
    "stage_storyboard",
    "stage_image_prompts",
    "stage_keyframes",
    "stage_transcribe",
    "stage_audio_transcribe",
}


class FilterChangeTransition:
    """Stateless model of a proposed filter change."""

    def __init__(self, conn, slug: str, new_filter: str | None, new_abstraction: int | None = None) -> None:
        self.conn = conn
        self.slug = slug
        self.new_filter = new_filter
        self.new_abstraction = new_abstraction

        # Fetch song row: filter, abstraction, world_brief, and scene count.
        song = self.conn.execute(
            "SELECT id, filter, abstraction, quality_mode, world_brief FROM songs WHERE slug = ?",
            (slug,),
        ).fetchone()
        if song is None:
            raise NotFoundError(f"Song '{slug}' not found")

        self.song_id = song["id"]
        self.current_filter = song["filter"]
        self.current_abstraction = song["abstraction"]
        self.current_quality_mode = song["quality_mode"]
        self.current_world_brief = song["world_brief"]

        scene_count = self.conn.execute(
            "SELECT COUNT(*) FROM scenes WHERE song_id = ?", (self.song_id,)
        ).fetchone()[0]
        self.scene_count = scene_count

    def kind(self) -> Literal["fresh-setup", "destructive", "noop"]:
        """Classify the type of transition."""
        # noop: visual language is already the target value.
        target_abstraction = self.new_abstraction if self.new_abstraction is not None else self.current_abstraction
        if self.new_filter == self.current_filter and target_abstraction == self.current_abstraction:
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
            f"""SELECT id FROM regen_runs
               WHERE song_id = ?
                 AND scope IN ({",".join("?" for _ in CONFLICT_SCOPES)})
                 AND status IN ('pending', 'running')
               LIMIT 1""",
            (self.song_id, *sorted(CONFLICT_SCOPES)),
        ).fetchone()

        if active:
            return f"chain already running, run {active['id']}"
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
        conflict_row = None
        reason = self.conflict_reason()
        if reason:
            conflict_row = self.conn.execute(
                f"""SELECT id FROM regen_runs
                   WHERE song_id = ?
                     AND scope IN ({",".join("?" for _ in CONFLICT_SCOPES)})
                     AND status IN ('pending', 'running')
                   LIMIT 1""",
                (self.song_id, *sorted(CONFLICT_SCOPES)),
            ).fetchone()
        would_conflict = (
            {
                "run_id": conflict_row["id"],
                "reason": reason,
            }
            if conflict_row
            else None
        )

        return {
            "kind": self.kind(),
            "from": {"filter": self.current_filter, "abstraction": self.current_abstraction},
            "to": {
                "filter": self.new_filter,
                "abstraction": self._resolved_abstraction(),
            },
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

    def apply(self) -> dict:
        """Apply the filter change and enqueue the filter regeneration chain.

        Returns a small result dict containing the resolved kind and run id.
        The caller remains responsible for serialising the updated song detail.
        """
        kind = self.kind()
        if kind == "noop":
            return {"kind": kind, "run_id": None}

        reason = self.conflict_reason()
        if reason is not None:
            raise ConflictError(reason)

        resolved_abstraction = self._resolved_abstraction()
        self.conn.execute(
            "UPDATE songs SET filter = ?, abstraction = ?, updated_at = ? WHERE id = ?",
            (self.new_filter, resolved_abstraction, time.time(), self.song_id),
        )

        if kind == "destructive":
            rows = self.conn.execute(
                "SELECT id, dirty_flags FROM scenes WHERE song_id = ? "
                "AND selected_clip_take_id IS NOT NULL",
                (self.song_id,),
            ).fetchall()
            for r in rows:
                flags = set(json.loads(r["dirty_flags"] or "[]"))
                flags.add("clip_stale")
                self.conn.execute(
                    "UPDATE scenes SET dirty_flags = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(sorted(flags)), time.time(), r["id"]),
                )

        self.conn.execute(
            "UPDATE songs SET world_brief = NULL, sequence_arc = NULL, updated_at = ? "
            "WHERE id = ?",
            (time.time(), self.song_id),
        )

        from ..generation import run_generation_stage
        from ..regen.queue import RegenJob, keyframe_queue
        from ..regen.runs import create_run, get_run
        from ..rendering import run_render_stage

        run_id = create_run(self.conn, scope="song_filter", song_id=self.song_id)
        run = get_run(self.conn, run_id)
        assert run is not None

        slug = self.slug
        async def handler(r):  # noqa: ANN001
            import asyncio
            loop = asyncio.get_event_loop()
            def run_chain():
                for generation_stage in ("world-brief", "storyboard", "image-prompts"):
                    result = run_generation_stage(
                        song_slug=slug,
                        stage=generation_stage,  # type: ignore[arg-type]
                        source_run_id=r.id,
                    )
                    if not result.ok:
                        return result
                return run_render_stage(
                    song_slug=slug,
                    stage="keyframes",
                    source_run_id=r.id,
                )
            return await loop.run_in_executor(
                None,
                run_chain,
            )

        keyframe_queue.submit(RegenJob(run=run, handler=handler))
        return {"kind": kind, "run_id": run_id}

    def _resolved_abstraction(self) -> int:
        if self.new_abstraction is not None:
            return self.new_abstraction
        if self.current_abstraction is not None:
            return self.current_abstraction
        return 0
