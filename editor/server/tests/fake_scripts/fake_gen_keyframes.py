"""Fake gen_keyframes.py for pipeline tests.

Mirrors the real script's argparse + stdout shape so the editor's
subprocess_runner + rescan paths exercise real code. Writes:
- character_brief.json  (Pass A output)
- storyboard.json       (Pass C output, one shot entry per scene)
- image_prompts.json    (Pass B output)
- keyframes/keyframe_NNN.png  (tiny valid-looking PNG per scene)

Emits the same stdout prefixes the real script uses:
    [Pass A] cached: ...
    [Pass A] 0.1s — ...
    [Pass C] cached: ...
    [Pass C] 0.1s — 2 beats
    [shot   1] Pass B 0.1s: ...
    [shot   1] keyframe 0.1s -> keyframe_001.png
    [done]

This avoids Gemini calls while proving the editor orchestrates correctly.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
import zlib
from pathlib import Path


def _tiny_png(width: int = 8, height: int = 8) -> bytes:
    """Minimal valid PNG with deterministic content — no Pillow needed."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    raw = b"".join(b"\x00" + b"\xa0\xa0\xa0" * width for _ in range(height))
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", required=True)
    ap.add_argument("--lyrics", required=True)
    ap.add_argument("--shots", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--filter", dest="filter_word", required=True)
    ap.add_argument("--abstraction", type=int, default=25)
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    keyframes_dir = run_dir / "keyframes"
    keyframes_dir.mkdir(exist_ok=True)

    shots_data = json.loads(Path(args.shots).read_text())
    shots = shots_data["shots"]

    # Pass A
    brief_path = run_dir / "character_brief.json"
    if brief_path.exists():
        print("[Pass A] cached: fake brief ...")
    else:
        t0 = time.time()
        brief_path.write_text(json.dumps({
            "brief": f"Fake world brief for {args.song} filter={args.filter_word} abs={args.abstraction}",
            "filter": args.filter_word,
            "abstraction": args.abstraction,
            "latency_s": round(time.time() - t0, 2),
        }, indent=2))
        print(f"[Pass A] {time.time() - t0:.1f}s — fake brief generated")

    # Pass C
    storyboard_path = run_dir / "storyboard.json"
    if storyboard_path.exists():
        storyboard = json.loads(storyboard_path.read_text())
        print(f"[Pass C] cached: {len(storyboard.get('shots', []))} shot beats")
    else:
        t0 = time.time()
        storyboard = {
            "sequence_arc": "fake arc",
            "shots": [
                {
                    "index": s["index"],
                    "beat": f"fake beat {s['index']}",
                    "camera_intent": "static hold",
                    "subject_focus": "the narrator",
                    "prev_link": None,
                    "next_link": None,
                }
                for s in shots
            ],
        }
        storyboard_path.write_text(json.dumps(storyboard, indent=2))
        print(f"[Pass C] {time.time() - t0:.1f}s — {len(storyboard['shots'])} beats")

    # Pass B + keyframe per shot
    image_prompts_path = run_dir / "image_prompts.json"
    image_prompts = (
        json.loads(image_prompts_path.read_text())
        if image_prompts_path.exists() else {}
    )
    for s in shots:
        idx = s["index"]
        kf_path = keyframes_dir / f"keyframe_{idx:03d}.png"
        if kf_path.exists():
            continue
        ip_key = f"shot_{idx:03d}"
        if ip_key not in image_prompts:
            t0 = time.time()
            image_prompts[ip_key] = (
                f"fake prompt for shot {idx} ({args.filter_word})"
            )
            image_prompts_path.write_text(json.dumps(image_prompts, indent=2))
            print(f"[shot {idx:3d}] Pass B {time.time() - t0:.1f}s: "
                  f"{image_prompts[ip_key][:80]}...")
        t0 = time.time()
        kf_path.write_bytes(_tiny_png())
        print(f"[shot {idx:3d}] keyframe {time.time() - t0:.1f}s -> {kf_path.name}")

    print(f"\n[done] keyframes in {keyframes_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
