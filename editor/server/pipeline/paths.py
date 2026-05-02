"""Path helpers for pipeline handlers.

Songs live under `OUTPUTS_DIR/<slug>/`. Each subprocess needs an absolute
path for --run-dir, --shots, --lyrics, --audio. `resolve_song_paths` derives
them consistently for both stages.py and regen.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SongPaths:
    """Absolute product paths for a given song."""
    run_dir: Path
    music_wav: Path
    lyrics_txt: Path
    shots_json: Path
    world_brief_json: Path
    storyboard_json: Path
    image_prompts_json: Path
    keyframes_dir: Path
    clips_dir: Path

    @property
    def has_world_brief(self) -> bool:
        return self.world_brief_json.exists()

    @property
    def has_storyboard(self) -> bool:
        return self.storyboard_json.exists()

    @property
    def has_image_prompts(self) -> bool:
        return self.image_prompts_json.exists()


def resolve_song_paths(
    *, outputs_root: Path, music_root: Path, slug: str,
) -> SongPaths:
    run_dir = outputs_root / slug
    return SongPaths(
        run_dir=run_dir,
        music_wav=music_root / f"{slug}.wav",
        lyrics_txt=music_root / f"{slug}.txt",
        shots_json=run_dir / "shots.json",
        world_brief_json=run_dir / "character_brief.json",
        storyboard_json=run_dir / "storyboard.json",
        image_prompts_json=run_dir / "image_prompts.json",
        keyframes_dir=run_dir / "keyframes",
        clips_dir=run_dir / "clips",
    )
