"""Idempotently build the fresh-song fixtures used by transcribe e2e.

Two fixtures, both newly-created songs (no outputs/, no whisperx cache):

  fresh-song-with-lyrics  music/fresh-song-wl.wav + music/fresh-song-wl.txt
  fresh-song-no-lyrics    music/fresh-song-nl.wav (no .txt)

These drive the happy-path and missing-lyrics-blocked cases of the
transcribe e2e spec. Tiny silent WAVs so they're cheap to build and
copy at test setup time.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WL_DIR = HERE / "fresh-song-with-lyrics"
NL_DIR = HERE / "fresh-song-no-lyrics"

FRESH_SAMPLE_RATE = 22050
# Story 14 raised the audio_too_short floor to 1.0s, so the fresh-song
# fixtures need to clear that bar to exercise the happy path.
FRESH_DURATION_S = 1.5


def _minimal_wav(path: Path, seconds: float = FRESH_DURATION_S,
                 sample_rate: int = FRESH_SAMPLE_RATE) -> None:
    n_samples = int(seconds * sample_rate)
    n_channels = 1
    sample_width = 2
    data = b"\x00\x00" * n_samples
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


def build() -> None:
    # fresh-song-with-lyrics
    wl_music = WL_DIR / "music"
    _minimal_wav(wl_music / "fresh-song-wl.wav")
    (wl_music / "fresh-song-wl.txt").write_text(
        "first line of the fresh song\n"
        "second line wraps it up\n"
    )
    # fresh-song-no-lyrics
    nl_music = NL_DIR / "music"
    _minimal_wav(nl_music / "fresh-song-nl.wav")
    # No .txt on purpose.


if __name__ == "__main__":
    build()
    print(f"built {WL_DIR}", file=sys.stderr)
    print(f"built {NL_DIR}", file=sys.stderr)
