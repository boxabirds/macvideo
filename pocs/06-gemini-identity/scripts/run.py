#!/usr/bin/env python
"""POC 6 — Gemini identity consistency across 5 chained stills."""

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT_DIR = HERE / "outputs"
OUT_DIR.mkdir(exist_ok=True)

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
    print("ERROR: GEMINI_API_KEY not set.", file=sys.stderr)
    sys.exit(1)

from google import genai
from google.genai import types

MODEL_ID = "gemini-3.1-flash-image-preview"

PERFORMER = (
    "A weathered mariner, mid-50s, grey beard, heavy grey sou'wester jacket, "
    "clear blue eyes, weather-lined face"
)

SCENES = [
    ("01_bow", "standing at the bow of a small fishing trawler, grey sea, overcast dawn, 16mm grain, wide shot"),
    ("02_pub", "inside a dimly lit harbour pub, warm amber light, looking past camera, shallow focus, 16mm grain"),
    ("03_cliff", "on a rain-lashed cliff path, wind-whipped coat, distant lighthouse blinking, stormy sky, 16mm grain"),
    ("04_cabin", "below deck in the trawler's cabin, close framing, warm yellow lamp, wooden panels, 16mm grain"),
    ("05_lane", "walking a stone-walled village lane at dusk, slate rooftops, cool twilight light, 16mm grain"),
]

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

meta_entries = []
reference_bytes: list[bytes] = []  # grows as we generate more shots

for idx, (name, scene) in enumerate(SCENES):
    prompt = f"{PERFORMER}. {scene}. No text."
    print(f"\n=== {name} (references: {len(reference_bytes)}) ===")
    print(f"Prompt: {prompt[:120]}...")

    contents: list = []
    # Attach prior images as Parts so Gemini treats them as identity references
    for prior in reference_bytes:
        contents.append(types.Part.from_bytes(data=prior, mime_type="image/png"))
    contents.append(prompt)

    t0 = time.time()
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=contents,
    )
    dt = time.time() - t0
    print(f"  response in {dt:.2f}s")

    image_bytes = None
    for part in response.candidates[0].content.parts:
        if getattr(part, "inline_data", None) is not None:
            image_bytes = part.inline_data.data
            break

    if image_bytes is None:
        print(f"  ERROR: no image returned for {name}", file=sys.stderr)
        meta_entries.append({"name": name, "prompt": prompt, "error": "no image"})
        continue

    out_path = OUT_DIR / f"{name}.png"
    out_path.write_bytes(image_bytes)
    print(f"  saved {out_path} ({len(image_bytes):,} bytes)")
    reference_bytes.append(image_bytes)

    meta_entries.append({
        "name": name,
        "prompt": prompt,
        "latency_s": round(dt, 2),
        "bytes": len(image_bytes),
        "reference_count": len(reference_bytes) - 1,
        "usage_metadata": (
            response.usage_metadata.model_dump()
            if getattr(response, "usage_metadata", None) else None
        ),
    })

meta = {"model": MODEL_ID, "performer": PERFORMER, "shots": meta_entries}
(OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
print(f"\nMetadata saved to {OUT_DIR / 'meta.json'}")
print(f"Open all: open {OUT_DIR}/*.png")
