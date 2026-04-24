"""Regenerate any portrait-oriented keyframe as landscape by prepending a
cinematic-widescreen directive to the cached Pass B prompt.

Gemini 3.1 flash image preview picks its aspect ratio from prompt content; on
papercut-style prompts it often chooses portrait for vertical dioramas.
Explicit landscape language biases it back to 16:9.

Usage:
    python regen_portrait_keyframes.py --run-dir outputs/busy-invisible
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent
ENV = REPO / ".env"
if ENV.exists():
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
if "GEMINI_API_KEY" not in os.environ:
    sys.exit("GEMINI_API_KEY not set")

from google import genai
from google.genai import types

IMG_MODEL = "gemini-3.1-flash-image-preview"
IMG_CONFIG = {
    "response_modalities": ["IMAGE", "TEXT"],
    "image_config": {"aspect_ratio": "16:9", "image_size": "1K"},
}
# Prompt prefix is belt-and-braces; aspect_ratio config is the actual enforcer.
LANDSCAPE_PREFIX = "Cinematic wide 16:9 landscape composition. "
IDENTITY_REF_WINDOW = 4


def is_portrait(path: Path) -> bool:
    with Image.open(path) as im:
        return im.size[1] > im.size[0]


def regen(client, prompt: str, refs: list[bytes], attempts: int = 3) -> bytes | None:
    for n in range(1, attempts + 1):
        contents: list = []
        for r in refs:
            contents.append(types.Part.from_bytes(data=r, mime_type="image/png"))
        contents.append(prompt)
        try:
            resp = client.models.generate_content(model=IMG_MODEL, contents=contents, config=IMG_CONFIG)
        except Exception as e:
            print(f"  attempt {n}: {e}", file=sys.stderr)
            time.sleep(2)
            continue
        cands = getattr(resp, "candidates", None) or []
        if not cands:
            time.sleep(2); continue
        parts = getattr(cands[0].content, "parts", None) or []
        for p in parts:
            if getattr(p, "inline_data", None) is not None:
                return p.inline_data.data
        time.sleep(2)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    kf_dir = run_dir / "keyframes"
    prompts = json.loads((run_dir / "image_prompts.json").read_text())

    portrait_shots = []
    for p in sorted(kf_dir.glob("keyframe_*.png")):
        idx = int(p.stem.split("_")[1])
        if is_portrait(p):
            portrait_shots.append(idx)

    print(f"Found {len(portrait_shots)} portrait keyframes: {portrait_shots}")
    if args.dry_run or not portrait_shots:
        return

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    for idx in portrait_shots:
        key = f"shot_{idx:03d}"
        pb = prompts.get(key)
        if not pb:
            print(f"  #{idx}: no Pass B prompt cached; skipping"); continue

        # Build identity-ref window from prior LANDSCAPE keyframes (skip the
        # portrait ones — they'd bias Gemini back to portrait)
        refs = []
        j = idx - 1
        while j >= 1 and len(refs) < IDENTITY_REF_WINDOW:
            prev = kf_dir / f"keyframe_{j:03d}.png"
            if prev.exists() and not is_portrait(prev):
                refs.insert(0, prev.read_bytes())
            j -= 1
        print(f"  #{idx}: {len(refs)} landscape refs")

        prompt = LANDSCAPE_PREFIX + pb
        t0 = time.time()
        img = regen(client, prompt, refs)
        if img is None:
            print(f"  #{idx}: FAILED no image returned"); continue
        out = kf_dir / f"keyframe_{idx:03d}.png"
        # Back up original
        backup = kf_dir.parent / "keyframes_portrait_backup" / out.name
        backup.parent.mkdir(exist_ok=True)
        if not backup.exists():
            out.rename(backup)
        out.write_bytes(img)
        # Verify new orientation
        with Image.open(out) as im:
            orient = "landscape" if im.size[0] > im.size[1] else "portrait"
            print(f"  #{idx}: regenerated in {time.time()-t0:.1f}s -> {im.size} ({orient})")


if __name__ == "__main__":
    main()
