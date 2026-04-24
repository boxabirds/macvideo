"""Fake render_clips.py for pipeline tests.

Writes a tiny valid-looking mp4 per scene (just enough bytes to satisfy
the editor's >100-byte size check) plus a final.mp4 in run_dir. Emits the
real script's stdout prefixes so subprocess_runner's parser sees:
    [shot   1] clip OK (0s, 9f)
    [done]

Avoids invoking LTX / mlx-video which requires GPU + model downloads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# A minimal fake mp4 payload. Real mp4 files start with an ftyp box; this
# content is NOT a valid mp4 (we don't need real playback in tests) but the
# editor's size check is >100 bytes and the file-exists check is enough.
_FAKE_MP4_BYTES = b"\x00\x00\x00\x1cftypisom" + b"\x00" * 512


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--shots", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--filter", dest="filter_word", required=True)
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--quality-mode", choices=["draft", "final"], default=None)
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    clips_dir = run_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    shots_data = json.loads(Path(args.shots).read_text())
    shots = shots_data["shots"]

    for s in shots:
        idx = s["index"]
        clip = clips_dir / f"clip_{idx:03d}.mp4"
        if clip.exists() and clip.stat().st_size > 100:
            continue
        clip.write_bytes(_FAKE_MP4_BYTES)
        print(f"[shot {idx:3d}] clip OK (0s, {s.get('num_frames', 9)}f)")

    # Drop a final.mp4 so the editor's story 10 handler can link it.
    final = run_dir / "final.mp4"
    final.write_bytes(_FAKE_MP4_BYTES * 2)
    print(f"\n[done] {final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
