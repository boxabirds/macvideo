"""POC 28 v2 — the CORRECT approach.

Prior v1 finding (user-corrected): asking Gemini for a "zoom-destination
composition" gave us content crossfades, not zooms. LTX interpolates
appearance, not camera pose — so the end frame must be GEOMETRICALLY
derived from the start (a zoomed crop) for LTX to infer camera motion.

This script:
  1. PIL-crops the start image around a zoom target (window / bird / narrator)
  2. Upscales the crop back to full canvas → this has the geometric signal of
     "camera zoomed in 2x on target"
  3. Feeds that zoomed-crop to Gemini with an img2img prompt that SAYS:
     keep framing/scale/composition exactly; only change the content
     (kitchen → misty field at dawn)
  4. Gemini output is therefore both:
     - geometrically "zoomed start" (same framing as PIL crop)
     - content-morphed into scene B (Gemini replaced kitchen with field)

LTX should now see geometric zoom + content morph = real push-through.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent.parent
REPO_ROOT = HERE.parent.parent
ENV_FILE = REPO_ROOT / ".env"

if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

if "GEMINI_API_KEY" not in os.environ:
    sys.exit("ERROR: GEMINI_API_KEY not set")

from google import genai
from google.genai import types

MODEL_ID = "gemini-3.1-flash-image-preview"
ZOOM_FACTOR = 2.0  # 2x zoom → crop to 1/4 area centered on target

START_SRC = (
    REPO_ROOT / "pocs" / "13-combined" / "outputs" / "latest" / "keyframe_01.png"
).resolve()

# Fractional coordinates of the zoom centre (x, y) in [0, 1]
TARGETS = [
    {
        "name": "geo_window",
        "label": "geometric zoom into window, content morph to field",
        "center_frac": (0.18, 0.50),
        "scene_b": (
            "an open misty field at dawn seen through the window's light — "
            "distant charcoal-smudged hills, chalky dawn mist, a single pale "
            "beam of directional light. A lone narrator-silhouette appears in "
            "the distance, same cross-hatched character as before. No bird, "
            "no interior, no table."
        ),
    },
    {
        "name": "geo_bird",
        "label": "geometric zoom into bird area, content morph to dispersing-bird field",
        "center_frac": (0.60, 0.60),
        "scene_b": (
            "the same space now an open misty field at dawn — the blackbird "
            "is mid-dispersal into scattered ink particles carried on the "
            "wind, charcoal-smudged hills behind, chalky mist, a lone "
            "narrator-silhouette watches in the distance. No interior, no table."
        ),
    },
    {
        "name": "geo_narrator",
        "label": "geometric zoom into narrator's face, content morph to narrator in field",
        "center_frac": (0.48, 0.45),
        "scene_b": (
            "the same weary cross-hatched narrator now outdoors, standing in "
            "an open misty field at dawn — same face, same clothing, same "
            "angle and framing. Behind him: distant charcoal-smudged hills "
            "and chalky dawn mist. No bird, no interior, no table."
        ),
    },
]


def geo_zoom(src: Image.Image, center_frac: tuple[float, float], zoom: float) -> Image.Image:
    """Center-crop at the target point to 1/zoom² area, upscale to original dims."""
    w, h = src.size
    new_w = int(round(w / zoom))
    new_h = int(round(h / zoom))
    cx = int(round(center_frac[0] * w))
    cy = int(round(center_frac[1] * h))
    x0 = max(0, min(w - new_w, cx - new_w // 2))
    y0 = max(0, min(h - new_h, cy - new_h // 2))
    crop = src.crop((x0, y0, x0 + new_w, y0 + new_h))
    return crop.resize((w, h), resample=Image.BICUBIC)


PROMPT_TEMPLATE = (
    "You are given a reference image that is a zoomed-in crop of a charcoal "
    "drawing (kitchen interior with a bald narrator and a blackbird). Your "
    "task: generate a new image with EXACTLY the same framing, composition, "
    "subject scale, subject position, camera angle, and shot size as the "
    "reference. Do NOT recompose. Do NOT change the scale of any subject. "
    "Do NOT re-frame.\n\n"
    "The ONLY change you must make: replace the kitchen interior content "
    "with {scene_b}\n\n"
    "Keep the exact charcoal-on-heavy-tooth-paper style from the reference: "
    "dense cross-hatching, soft rubbed-out edges, monochromatic deep soot, "
    "grainy mid-tones, stark white highlights. The result should feel like "
    "the SAME SHOT, same zoom level, same framing, but with kitchen → field "
    "content substitution."
)


def main() -> None:
    if not START_SRC.exists():
        sys.exit(f"missing {START_SRC}")

    kf_dir = HERE / "keyframes_v2"
    kf_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(START_SRC, kf_dir / "start.png")

    src = Image.open(START_SRC).convert("RGB")

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    for t in TARGETS:
        print(f"\n=== {t['name']} — {t['label']} ===")

        # Step 1: PIL geometric zoom
        zoomed = geo_zoom(src, t["center_frac"], ZOOM_FACTOR)
        zoomed_path = kf_dir / f"{t['name']}_zoomed_crop.png"
        zoomed.save(zoomed_path, format="PNG")
        print(f"  wrote geometric zoom crop: {zoomed_path.name}")

        # Step 2: Gemini content morph
        prompt = PROMPT_TEMPLATE.format(scene_b=t["scene_b"])
        contents: list = [
            types.Part.from_bytes(data=zoomed_path.read_bytes(), mime_type="image/png"),
            prompt,
        ]
        t0 = time.time()
        response = client.models.generate_content(model=MODEL_ID, contents=contents)
        dt = time.time() - t0
        print(f"  Gemini response in {dt:.2f}s")

        image_bytes = None
        for part in response.candidates[0].content.parts:
            if getattr(part, "inline_data", None) is not None:
                image_bytes = part.inline_data.data
                break
        if image_bytes is None:
            print(f"  ERROR: no image for {t['name']}", file=sys.stderr)
            continue

        out_path = kf_dir / f"end_{t['name']}.png"
        out_path.write_bytes(image_bytes)
        print(f"  wrote end image: {out_path.name} ({len(image_bytes):,} bytes)")


if __name__ == "__main__":
    main()
