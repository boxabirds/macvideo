"""Pure functions that compute dirty-flag transitions.

Called from API handlers (edit writes, take arrivals) and from stage runners
(filter / abstraction / world-brief changes). Keeping them pure and side-effect
free makes them trivially unit-testable and lets callers batch-apply results
in a single transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .schema import DirtyFlag


# Fields whose mutation invalidates a scene's keyframe + clip on that scene.
# target_text was added when the frontend gained editable lyric override
# (widens Story 3 PRD which marked target_text as read-only).
_LOCAL_REGEN_FIELDS = {
    "beat", "camera_intent", "subject_focus", "image_prompt", "target_text",
}

# Fields whose mutation also ripples up the identity chain (N+1..N+4).
# target_text participates because the lyric drives prompt generation for
# the identity window.
_IDENTITY_CHAIN_FIELDS = {"beat", "camera_intent", "subject_focus", "target_text"}

# How many downstream neighbours share a keyframe's identity chain.
IDENTITY_REF_WINDOW = 4


@dataclass(frozen=True)
class SceneFieldEdit:
    """One user-initiated edit to a single scene's field."""
    scene_index: int
    field_name: str
    reverted_to_saved: bool = False  # True if new value equals last persisted value


@dataclass(frozen=True)
class SongLevelEdit:
    """An edit to the song's filter or abstraction."""
    kind: str   # 'filter' | 'abstraction'


@dataclass(frozen=True)
class TakeArrival:
    """A new take was written for a scene."""
    scene_index: int
    artefact_kind: str      # 'keyframe' | 'clip'
    prompt_snapshot: Optional[str]
    current_image_prompt: Optional[str]
    # For clip takes, the selected keyframe at time of render.
    source_keyframe_take_id: Optional[int] = None
    current_selected_keyframe_take_id: Optional[int] = None


def flags_after_scene_edit(current_flags: Iterable[str],
                           edit: SceneFieldEdit,
                           total_scene_count: int) -> tuple[set[str], dict[int, set[str]]]:
    """Compute the scene's new dirty flags + any propagated flags to
    identity-chain neighbours.

    Returns: (flags_for_this_scene, {neighbour_scene_index: flags_for_that_scene})
    """
    flags = set(current_flags)
    neighbours: dict[int, set[str]] = {}

    if edit.field_name not in _LOCAL_REGEN_FIELDS:
        return flags, neighbours

    if edit.reverted_to_saved:
        # Revert clears its own staleness — but ONLY if the field-change
        # was the one that set the flag. Caller checks whether other recent
        # edits might have dirtied this scene for other reasons.
        flags.discard(DirtyFlag.keyframe_stale.value)
        flags.discard(DirtyFlag.clip_stale.value)
        return flags, neighbours

    flags.add(DirtyFlag.keyframe_stale.value)
    flags.add(DirtyFlag.clip_stale.value)

    if edit.field_name in _IDENTITY_CHAIN_FIELDS:
        for offset in range(1, IDENTITY_REF_WINDOW + 1):
            nb = edit.scene_index + offset
            if nb <= total_scene_count:
                neighbours[nb] = {DirtyFlag.keyframe_stale.value}

    return flags, neighbours


def flags_after_song_level_edit(current_flags_per_scene: dict[int, Iterable[str]],
                                edit: SongLevelEdit) -> dict[int, set[str]]:
    """Filter or abstraction change invalidates everything.

    Returns a dict mapping scene_index -> new flags set.
    """
    result: dict[int, set[str]] = {}
    for idx, flags in current_flags_per_scene.items():
        new = set(flags)
        new.add(DirtyFlag.keyframe_stale.value)
        new.add(DirtyFlag.clip_stale.value)
        result[idx] = new
    return result


def flags_after_take_arrival(current_flags: Iterable[str],
                             arrival: TakeArrival) -> set[str]:
    """A fresh take may or may not clear its corresponding stale flag.

    A keyframe take clears `keyframe_stale` iff its prompt_snapshot equals
    the scene's current image_prompt. A clip take clears `clip_stale` iff
    its source keyframe equals the scene's currently-selected keyframe.
    """
    flags = set(current_flags)

    if arrival.artefact_kind == "keyframe":
        if (arrival.prompt_snapshot is not None
                and arrival.current_image_prompt is not None
                and arrival.prompt_snapshot == arrival.current_image_prompt):
            flags.discard(DirtyFlag.keyframe_stale.value)
    elif arrival.artefact_kind == "clip":
        if (arrival.source_keyframe_take_id is not None
                and arrival.source_keyframe_take_id == arrival.current_selected_keyframe_take_id):
            flags.discard(DirtyFlag.clip_stale.value)

    return flags
