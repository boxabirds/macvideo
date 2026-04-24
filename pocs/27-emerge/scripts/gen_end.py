"""Generate POC 27's end keyframe via Gemini using POC 13 keyframe as identity ref.

End scene = narrator alone in an open misty field at dawn, no bird. Same charcoal
filter, same character. This is the scene we'll ask LTX to MORPH into from the
kitchen-table start frame under 4 different trajectory prompts.
"""

from __future__ import annotations

import os
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

END_PROMPT = (
    "The same weary, cross-hatched narrator from the reference image now stands "
    "alone in an open misty field at dawn, no bird present, no interior, no "
    "table. He is a lone silhouette in heavy-tooth paper charcoal, dense "
    "cross-hatching on his form, soft rubbed-out edges. Distant charcoal-smudged "
    "hills on the horizon, chalky dawn mist curling around his feet, a single "
    "beam of pale directional light from the side. Every surface is the same "
    "monochromatic palette of deep soot, grainy mid-tones, stark white highlights. "
    "Wide composition matching the reference's framing."
)


def main() -> None:
    if not START_SRC.exists():
        sys.exit(f"missing {START_SRC}")

    out_dir = HERE / "keyframes"
    out_dir.mkdir(parents=True, exist_ok=True)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    ref_bytes = START_SRC.read_bytes()

    contents: list = [
        types.Part.from_bytes(data=ref_bytes, mime_type="image/png"),
        END_PROMPT,
    ]
    t0 = time.time()
    response = client.models.generate_content(model=MODEL_ID, contents=contents)
    dt = time.time() - t0
    print(f"Gemini response in {dt:.2f}s")

    image_bytes = None
    for part in response.candidates[0].content.parts:
        if getattr(part, "inline_data", None) is not None:
            image_bytes = part.inline_data.data
            break
    if image_bytes is None:
        sys.exit("no image returned")

    out_path = out_dir / "end_field.png"
    out_path.write_bytes(image_bytes)
    (out_dir / "start_table.png").write_bytes(ref_bytes)
    print(f"Wrote {out_path} ({len(image_bytes):,} bytes)")
    print(f"Wrote {out_dir / 'start_table.png'} (copy of start)")


if __name__ == "__main__":
    main()
