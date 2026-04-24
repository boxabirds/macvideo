"""POC 28 — generate 3 end-image variants via Gemini using different zoom-morph
prompting strategies.

Hypothesis: an end image whose COMPOSITION reads as "zoomed into a specific
detail of the start image" will produce a more continuous-looking push-in morph
than a generic "different scene at matched framing" end image.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

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

START_SRC = (
    REPO_ROOT / "pocs" / "13-combined" / "outputs" / "latest" / "keyframe_01.png"
).resolve()

VARIANTS = [
    {
        "name": "v1_naive",
        "label": "Naive (reuse POC 27 approach)",
        "prompt": (
            "The same weary, cross-hatched narrator from the reference image now "
            "stands alone in an open misty field at dawn, no bird present, no "
            "interior, no table. He is a lone silhouette in heavy-tooth paper "
            "charcoal, dense cross-hatching on his form, soft rubbed-out edges. "
            "Distant charcoal-smudged hills on the horizon, chalky dawn mist "
            "curling around his feet, a single beam of pale directional light "
            "from the side. Every surface is the same monochromatic palette of "
            "deep soot, grainy mid-tones, stark white highlights. Wide composition "
            "matching the reference's framing."
        ),
    },
    {
        "name": "v2_zoom_window",
        "label": "Zoom-through-window (portal composition)",
        "prompt": (
            "Generate an image that would feel like the DESTINATION of a "
            "continuous zoom-and-morph push-in from the reference image. The "
            "camera has pushed forward THROUGH THE WINDOW visible on the left "
            "side of the reference; as it pushed, the kitchen interior dissolved "
            "and the view through the window expanded to fill the entire frame.\n\n"
            "The generated image should:\n"
            "1. Feel compositionally like a tightened, pushed-in framing where "
            "the reference's LEFT-SIDE WINDOW REGION has become the whole frame. "
            "The window frame itself should no longer be visible — we're now "
            "past it, inside what it was looking out onto.\n"
            "2. Show a misty open field at dawn — distant charcoal-smudged hills, "
            "chalky dawn mist curling across grassy ground, a single pale beam "
            "of directional light from the side.\n"
            "3. Place the same weary narrator from the reference now standing "
            "alone in this field as a lone silhouette, no bird, no table, no "
            "interior. He has walked forward through the window into the "
            "landscape.\n"
            "4. Preserve the exact charcoal-on-heavy-tooth-paper style from "
            "the reference: dense cross-hatching, soft rubbed-out edges, "
            "monochromatic palette of deep soot, grainy mid-tones, stark white "
            "highlights.\n"
            "5. Feel like the final frame of a 3-second continuous forward "
            "push-in from the reference — the motion direction and framing "
            "should feel like a natural conclusion to that push."
        ),
    },
    {
        "name": "v3_zoom_bird",
        "label": "Zoom-through-bird (morphing subject)",
        "prompt": (
            "Generate an image that would feel like the DESTINATION of a "
            "continuous zoom-and-morph push-in from the reference image. The "
            "camera has pushed forward TOWARDS THE BLACKBIRD visible in the "
            "right-center of the reference; as it pushed, the bird's silhouette "
            "dispersed into scattered ink particles carried on the wind, and "
            "through that dispersal a new open landscape emerged.\n\n"
            "The generated image should:\n"
            "1. Feel compositionally like a tightened, pushed-in framing where "
            "the reference's BIRD-REGION has become the whole frame. The bird "
            "itself should be gone — dispersed, fragmented — but faint scattered "
            "dark particles on the wind echo where it was.\n"
            "2. Show a misty open field at dawn in that same region of the "
            "frame — distant charcoal-smudged hills, chalky dawn mist, a single "
            "pale beam of directional light from the side. The landscape grew "
            "OUT OF the bird as it dispersed.\n"
            "3. Place the same weary narrator from the reference now standing "
            "alone in this field as a lone silhouette, no bird present, no "
            "table, no interior.\n"
            "4. Preserve the exact charcoal-on-heavy-tooth-paper style from "
            "the reference: dense cross-hatching, soft rubbed-out edges, "
            "monochromatic palette of deep soot, grainy mid-tones, stark white "
            "highlights.\n"
            "5. Feel like the final frame of a 3-second continuous forward "
            "push-in from the reference, aimed at where the bird was."
        ),
    },
]


def main() -> None:
    if not START_SRC.exists():
        sys.exit(f"missing {START_SRC}")

    keyframes_dir = HERE / "keyframes"
    keyframes_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(START_SRC, keyframes_dir / "start.png")

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    ref_bytes = START_SRC.read_bytes()

    for v in VARIANTS:
        print(f"\n=== {v['name']} — {v['label']} ===")
        contents: list = [
            types.Part.from_bytes(data=ref_bytes, mime_type="image/png"),
            v["prompt"],
        ]
        t0 = time.time()
        response = client.models.generate_content(model=MODEL_ID, contents=contents)
        dt = time.time() - t0
        print(f"  response in {dt:.2f}s")

        image_bytes = None
        for part in response.candidates[0].content.parts:
            if getattr(part, "inline_data", None) is not None:
                image_bytes = part.inline_data.data
                break
        if image_bytes is None:
            print(f"  ERROR: no image for {v['name']}", file=sys.stderr)
            continue

        out_path = keyframes_dir / f"end_{v['name']}.png"
        out_path.write_bytes(image_bytes)
        print(f"  wrote {out_path} ({len(image_bytes):,} bytes)")


if __name__ == "__main__":
    main()
