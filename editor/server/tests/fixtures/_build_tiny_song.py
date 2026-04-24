"""Idempotently build the tiny-song fixture tree used by integration tests."""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TINY = HERE / "tiny-song"


def _minimal_wav(path: Path, seconds: float = 0.5, sample_rate: int = 22050):
    """Write a tiny valid WAV file with silence. Enough to probe duration."""
    n_samples = int(seconds * sample_rate)
    n_channels = 1
    sample_width = 2
    data = b"\x00\x00" * n_samples
    # RIFF WAVE PCM header
    header = b"RIFF"
    header += struct.pack("<I", 36 + len(data))
    header += b"WAVE"
    header += b"fmt "
    header += struct.pack("<IHHIIHH", 16, 1, n_channels, sample_rate,
                          sample_rate * n_channels * sample_width,
                          n_channels * sample_width, sample_width * 8)
    header += b"data"
    header += struct.pack("<I", len(data))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + data)


_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c62000100000005000100200f0c3e000000004945"
    "4e44ae426082"
)


def _tiny_png(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_PNG_1x1)


def build():
    music = TINY / "music"
    outputs = TINY / "outputs" / "tiny-song"
    keyframes = outputs / "keyframes"
    music.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    keyframes.mkdir(parents=True, exist_ok=True)

    # audio + lyrics
    _minimal_wav(music / "tiny-song.wav", seconds=0.5)
    (music / "tiny-song.txt").write_text("la la la\noh oh oh\nthe end\n")

    # shots.json — 2 scenes
    (outputs / "shots.json").write_text(json.dumps({
        "song": "tiny-song",
        "duration_s": 0.5,
        "fps": 30,
        "shot_count": 2,
        "total_covered_s": 0.5,
        "shots": [
            {
                "index": 1, "kind": "lyric", "target_text": "la la la",
                "start_s": 0.0, "end_s": 0.3,
                "target_duration_s": 0.3, "duration_s": 0.3, "num_frames": 9,
                "lyric_line_idx": 0,
            },
            {
                "index": 2, "kind": "lyric", "target_text": "oh oh oh",
                "start_s": 0.3, "end_s": 0.5,
                "target_duration_s": 0.2, "duration_s": 0.3, "num_frames": 9,
                "lyric_line_idx": 1,
            },
        ],
    }, indent=2))

    (outputs / "character_brief.json").write_text(json.dumps({
        "brief": "A tiny test narrator stands in a tiny test room.",
        "filter": "charcoal",
        "abstraction": 25,
    }))

    # Active storyboard.json with prev/next links MISSING (simulating remap bug)
    (outputs / "storyboard.json").write_text(json.dumps({
        "sequence_arc": "tiny arc",
        "shots": [
            {"index": 1, "target_text": "la la la", "beat": "beat one",
             "camera_intent": "static hold", "subject_focus": "narrator",
             "prev_link": None, "next_link": None},
            {"index": 2, "target_text": "oh oh oh", "beat": "beat two",
             "camera_intent": "slow push in", "subject_focus": "narrator",
             "prev_link": None, "next_link": None},
        ],
    }))

    # .24fps.bak holds the ORIGINAL links that were stripped by the bug
    (outputs / "storyboard.json.24fps.bak").write_text(json.dumps({
        "sequence_arc": "tiny arc",
        "shots": [
            {"index": 1, "prev_link": None, "next_link": "Leading into beat two"},
            {"index": 2, "prev_link": "Following beat one", "next_link": None},
        ],
    }))

    (outputs / "image_prompts.json").write_text(json.dumps({
        "shot_001": "a tiny test narrator in a tiny test room, charcoal style",
        "shot_002": "the narrator closer, charcoal style",
    }))

    _tiny_png(keyframes / "keyframe_001.png")
    _tiny_png(keyframes / "keyframe_002.png")

    print(f"built fixture at {TINY}")


if __name__ == "__main__":
    build()
    sys.exit(0)
