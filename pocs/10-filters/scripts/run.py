#!/usr/bin/env python
"""POC 10 v2 — stronger filter expansion + curated filter list.

v1 revealed that world-reskin filters (steampunk, bubblegum) were ignored:
Gemini treated them as decoration on a photoreal base rather than a full
reimagining. Two fixes applied here:

1. Expansion prompt explicitly tells the LLM to *reimagine* the subject
   entirely within the style, not decorate a realistic version.
2. Expansion output IS the full image prompt (no subject concatenation).
   The LLM owns the whole scene description, including how the subject
   appears within the style's world.
3. Curated filter list leans on medium-transforms (known to work) while
   still retesting world-reskin filters under the new prompt.
"""

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REPO_ROOT = HERE.parent.parent

sys.path.insert(0, str(REPO_ROOT))
from pocs._lib.poc_helpers import make_run_dir, save_prompts  # noqa: E402

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

LLM_MODEL = "gemini-3-flash-preview"
IMG_MODEL = "gemini-3.1-flash-image-preview"

SUBJECT = "a stone bridge arching over water"

# Curated: 3 medium-transforms known to work (v1), 2 new medium-transforms
# added for range, 2 world-reskin filters retried with the stronger prompt.
FILTERS = [
    "papercut",
    "watercolour",
    "pencil sketch",
    "charcoal",
    "stained glass",
    "steampunk",
    "bubblegum",
]

EXPAND_PROMPT = """You are a visual style director for a cinematic music video pipeline.

Your task: reimagine the following subject ENTIRELY within the "{word}" style.
The subject must not appear as a photorealistic scene decorated with "{word}"
elements — it must BE a "{word}" scene, composed of "{word}" materials, lit by
"{word}" lighting, depicted by "{word}" rules of mark-making.

Write a complete image-generation prompt (3-4 sentences) for this reimagined
scene. Use only concrete visual cues — specific materials, textures, hues (name
them), line quality, depth treatment, lighting behaviour. No emotional words,
no generic phrases like "in the style of". Describe what the eye literally sees.
Do not include "no people" or similar negatives unless they are intrinsic to
the style.

Subject to reimagine: {subject}
Style: {word}

Return ONLY the final image prompt, no preamble, no quotes."""


def expand_filter(client, word):
    t0 = time.time()
    response = client.models.generate_content(
        model=LLM_MODEL,
        contents=EXPAND_PROMPT.format(word=word, subject=SUBJECT),
    )
    dt = time.time() - t0
    return response.text.strip(), dt, response.usage_metadata


def generate_image(client, prompt, out_path):
    t0 = time.time()
    response = client.models.generate_content(
        model=IMG_MODEL,
        contents=prompt,
    )
    dt = time.time() - t0
    for part in response.candidates[0].content.parts:
        if getattr(part, "inline_data", None) is not None:
            out_path.write_bytes(part.inline_data.data)
            return True, dt, response.usage_metadata
    return False, dt, response.usage_metadata


def main():
    run_dir = make_run_dir(__file__)
    print(f"Run dir: {run_dir}")
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    meta = {"subject": SUBJECT, "llm_model": LLM_MODEL, "img_model": IMG_MODEL, "shots": []}
    expansions = {}

    # Reference (plain subject, no style)
    print("=== 00_reference ===")
    plain_prompt = (
        f"A wide cinematic photograph of {SUBJECT}, overcast soft light, no text"
    )
    out = run_dir / "00_reference.png"
    ok, dt, usage = generate_image(client, plain_prompt, out)
    print(f"  {'saved' if ok else 'FAILED'} in {dt:.2f} s")
    meta["shots"].append({
        "slot": "00_reference", "filter": None, "prompt": plain_prompt,
        "image_latency_s": round(dt, 2),
        "usage": usage.model_dump() if usage else None,
    })

    # Filters
    for idx, word in enumerate(FILTERS, start=1):
        name = word.replace(" ", "_")
        slot = f"{idx:02d}_{name}"
        print(f"\n=== {slot} ===")

        print(f"  expanding {word!r}...")
        full_prompt, llm_dt, llm_usage = expand_filter(client, word)
        print(f"  prompt: {full_prompt[:160]}{'...' if len(full_prompt) > 160 else ''}")
        expansions[word] = full_prompt

        out = run_dir / f"{slot}.png"
        ok, img_dt, img_usage = generate_image(client, full_prompt, out)
        print(f"  {'saved' if ok else 'FAILED'} in {img_dt:.2f} s")

        meta["shots"].append({
            "slot": slot, "filter": word,
            "prompt": full_prompt,
            "llm_latency_s": round(llm_dt, 2),
            "image_latency_s": round(img_dt, 2),
            "llm_usage": llm_usage.model_dump() if llm_usage else None,
            "img_usage": img_usage.model_dump() if img_usage else None,
        })

    (run_dir / "expansions.json").write_text(json.dumps(expansions, indent=2))
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    save_prompts(run_dir, {
        "subject": SUBJECT,
        "filters": FILTERS,
        "llm_expand_prompt_template": EXPAND_PROMPT,
        "llm_expansions": expansions,
        "image_prompts": {
            slot_name: next((s["prompt"] for s in meta["shots"] if s["slot"] == slot_name), None)
            for slot_name in [s["slot"] for s in meta["shots"]]
        },
    })
    print(f"\nAll outputs in {run_dir}")


if __name__ == "__main__":
    main()
