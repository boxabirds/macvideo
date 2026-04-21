#!/usr/bin/env python
"""POC 5 — Gemini gemini-3.1-flash-image-preview single still."""

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

# Load .env without adding python-dotenv as a dep
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

if "GEMINI_API_KEY" not in os.environ:
    print("ERROR: GEMINI_API_KEY not set. Put it in .env at repo root.", file=sys.stderr)
    sys.exit(1)

from google import genai

MODEL_ID = "gemini-3.1-flash-image-preview"
PROMPT = (
    "A weathered steampunk landscape: brass gears and riveted copper plates "
    "catching warm gaslamp glow, volumetric steam drifting across the frame, "
    "Victorian filigree silhouetted in the foreground, muted sepia-desaturated "
    "palette with warm amber highlights, cinematic wide shot, 16mm film grain, "
    "no figures, no text."
)

print(f"Model: {MODEL_ID}")
print(f"Prompt: {PROMPT[:100]}...")
print()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

t0 = time.time()
response = client.models.generate_content(
    model=MODEL_ID,
    contents=PROMPT,
)
latency_s = time.time() - t0

print(f"Response received in {latency_s:.2f} s")

# Extract image bytes from the response
image_saved = False
text_parts = []
for part in response.candidates[0].content.parts:
    if getattr(part, "inline_data", None) is not None:
        out = OUT_DIR / "still.png"
        out.write_bytes(part.inline_data.data)
        print(f"Saved image to {out} ({len(part.inline_data.data):,} bytes)")
        image_saved = True
    elif getattr(part, "text", None):
        text_parts.append(part.text)

if text_parts:
    print("Model also returned text (often caption or policy note):")
    for t in text_parts:
        print(f"  {t}")

meta = {
    "model": MODEL_ID,
    "prompt": PROMPT,
    "latency_s": round(latency_s, 2),
    "image_saved": image_saved,
    "text_parts": text_parts,
    "usage_metadata": (
        response.usage_metadata.model_dump()
        if getattr(response, "usage_metadata", None)
        else None
    ),
}
(OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
print(f"Saved metadata to {OUT_DIR / 'meta.json'}")

if not image_saved:
    print("ERROR: No image returned. See meta.json for response details.", file=sys.stderr)
    sys.exit(2)
