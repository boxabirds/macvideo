"""Product-owned scene plan reads.

Historical JSON files may seed these records through import paths, but normal
runtime reads use the saved database state as the source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenePlanRow:
    scene_index: int
    kind: str
    target_text: str
    start_s: float
    end_s: float
    target_duration_s: float
    num_frames: int
    lyric_line_idx: int | None
    beat: str | None
    camera_intent: str | None
    subject_focus: str | None
    image_prompt: str | None


@dataclass(frozen=True)
class ScenePlan:
    song_id: int
    slug: str
    scenes: list[ScenePlanRow]

    @property
    def empty(self) -> bool:
        return len(self.scenes) == 0

    def to_legacy_shots(self) -> dict:
        """Compatibility shape for temporary legacy generation adapters."""
        return {
            "shots": [
                {
                    "index": scene.scene_index,
                    "kind": scene.kind,
                    "target_text": scene.target_text,
                    "start_s": scene.start_s,
                    "end_s": scene.end_s,
                    "target_duration_s": scene.target_duration_s,
                    "duration_s": scene.target_duration_s,
                    "num_frames": scene.num_frames,
                    "lyric_line_idx": scene.lyric_line_idx,
                }
                for scene in self.scenes
            ],
        }


def load_song_scene_plan(conn, song_id: int) -> ScenePlan:
    song = conn.execute(
        "SELECT id, slug FROM songs WHERE id = ?",
        (song_id,),
    ).fetchone()
    if song is None:
        raise ValueError(f"song {song_id} not found")
    rows = conn.execute(
        """
        SELECT scene_index, kind, target_text, start_s, end_s,
               target_duration_s, num_frames, lyric_line_idx, beat,
               camera_intent, subject_focus, image_prompt
        FROM scenes
        WHERE song_id = ?
        ORDER BY scene_index
        """,
        (song_id,),
    ).fetchall()
    return ScenePlan(
        song_id=song["id"],
        slug=song["slug"],
        scenes=[
            ScenePlanRow(
                scene_index=row["scene_index"],
                kind=row["kind"],
                target_text=row["target_text"],
                start_s=row["start_s"],
                end_s=row["end_s"],
                target_duration_s=row["target_duration_s"],
                num_frames=row["num_frames"],
                lyric_line_idx=row["lyric_line_idx"],
                beat=row["beat"],
                camera_intent=row["camera_intent"],
                subject_focus=row["subject_focus"],
                image_prompt=row["image_prompt"],
            )
            for row in rows
        ],
    )
