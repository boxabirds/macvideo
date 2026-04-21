#!/usr/bin/env python
"""POC 14 — abstraction spectrum. Same line, same world, five abstraction levels."""

import json
import os
import re
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

LYRICS_PATH = REPO_ROOT / "music" / "my-little-blackbird.txt"
TARGET_LINE = "He's arrived again"
FILTER_WORD = "charcoal"
LLM_MODEL = "gemini-3-flash-preview"
IMG_MODEL = "gemini-3.1-flash-image-preview"

ABSTRACTION_LEVELS = [0, 25, 50, 75, 100]

ABSTRACTION_DESCRIPTORS = {
    0: "fully representational, photographic clarity, subjects rendered as concrete recognisable form with grounded proportions and depth",
    25: "loosely expressive — brushwork and line quality given primacy over accuracy; subjects still clearly legible but simplified; distortion and gesture honoured",
    50: "heavily stylised — figures become simplified masses and volumes, architecture reduced to structural shapes; recognisable but abstracted",
    75: "predominantly abstract — the figure becomes a dark mass or smear, the setting becomes rectangles of light and shadow, details replaced by rhythm and weight",
    100: "pure abstraction — no recognisable figures, objects, or settings; composition is colour field, line, rhythm, texture",
}

PASS_A_PROMPT = """You are a music video director. Read the song carefully.

Song lyrics:
---
{lyrics}
---

The video will be rendered in the "{filter_word}" style.

Write a short "character & world brief" (5-8 sentences) that every shot of
this song must honour. Describe:
 - The narrator: appearance, age, clothing, demeanour (specific visual cues only)
 - The central metaphorical subject as a visible entity (here: the blackbird)
 - The primary setting / world (domestic? exterior? atmospheric qualities)
 - How the "{filter_word}" style manifests on all of the above (materials,
   textures, line quality, palette, lighting)

Use concrete visual language only — no emotional labels. Describe what IS
present, never what is absent. This brief is the anchor for per-shot prompts.

Return ONLY the brief, as a single paragraph. No preamble, no quotes."""

PASS_B_PROMPT = """You are a music video director generating one keyframe image prompt.

Song lyrics:
---
{lyrics}
---

Persistent character & world brief (applies to EVERY shot of this song):
---
{brief}
---

Target line for this shot: "{target_line}"

Abstraction level: {abstraction}/100.
Apply this abstraction level as a visual instruction: {abstraction_descriptor}

Write ONE image-generation prompt (3-4 sentences) for a keyframe representing
this line in the context of the full song. Describe what IS present in the
frame — materials, objects, atmosphere, motion — at the specified abstraction
level. Use concrete visual cues only; no emotional labels. Never describe
absence; if the frame is empty of figures at high abstraction, describe the
positive forms that fill it (shapes, fields, rhythms).

Return ONLY the final image prompt as a single paragraph. No preamble, no quotes."""

SECTION_MARKER_RE = re.compile(r"^\*+\[[^\]]*\]\*+\s*$")


def clean_lyrics_for_llm(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        lines.append(s)
    return "\n".join(lines).strip()


def main():
    run_dir = make_run_dir(__file__, tag=FILTER_WORD)
    print(f"Run dir: {run_dir}")

    lyrics_text = clean_lyrics_for_llm(LYRICS_PATH.read_text())
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # Pass A
    print("\n=== Pass A: character & world brief ===")
    pass_a_input = PASS_A_PROMPT.format(lyrics=lyrics_text, filter_word=FILTER_WORD)
    t0 = time.time()
    brief_resp = client.models.generate_content(model=LLM_MODEL, contents=pass_a_input)
    brief_dt = time.time() - t0
    brief = brief_resp.text.strip()
    print(f"  {brief_dt:.2f} s — {brief[:180]}{'...' if len(brief) > 180 else ''}")
    (run_dir / "character_brief.json").write_text(
        json.dumps({"filter": FILTER_WORD, "brief": brief, "latency_s": round(brief_dt, 2)}, indent=2)
    )

    # Pass B × 5 (one per abstraction level), each independent (no identity chain — we want the spectrum)
    pass_b_inputs = {}
    image_prompts = {}
    for N in ABSTRACTION_LEVELS:
        slot = f"abstraction_{N:03d}"
        print(f"\n=== {slot} ===")
        pass_b_input = PASS_B_PROMPT.format(
            lyrics=lyrics_text,
            brief=brief,
            target_line=TARGET_LINE,
            abstraction=N,
            abstraction_descriptor=ABSTRACTION_DESCRIPTORS[N],
        )
        pass_b_inputs[slot] = pass_b_input

        t0 = time.time()
        resp = client.models.generate_content(model=LLM_MODEL, contents=pass_b_input)
        dt = time.time() - t0
        image_prompt = resp.text.strip().strip('"').strip()
        image_prompts[slot] = image_prompt
        print(f"  pass B ({dt:.2f} s): {image_prompt[:180]}{'...' if len(image_prompt) > 180 else ''}")

        t0 = time.time()
        img_resp = client.models.generate_content(model=IMG_MODEL, contents=image_prompt)
        img_dt = time.time() - t0
        image_bytes = None
        for part in img_resp.candidates[0].content.parts:
            if getattr(part, "inline_data", None) is not None:
                image_bytes = part.inline_data.data
                break
        if image_bytes is None:
            print(f"  ERROR: no image returned for {slot}", file=sys.stderr)
            continue
        out = run_dir / f"{slot}.png"
        out.write_bytes(image_bytes)
        print(f"  image saved ({img_dt:.2f} s, {len(image_bytes):,} bytes): {out.name}")

    save_prompts(run_dir, {
        "target_line": TARGET_LINE,
        "filter": FILTER_WORD,
        "abstraction_levels": ABSTRACTION_LEVELS,
        "abstraction_descriptors": ABSTRACTION_DESCRIPTORS,
        "pass_a_input": PASS_A_PROMPT,
        "pass_a_output_brief": brief,
        "pass_b_input_template": PASS_B_PROMPT,
        "pass_b_inputs_per_level": pass_b_inputs,
        "image_prompts_per_level": image_prompts,
        "identity_chain_used": False,
        "notes": "Cross-level identity chain intentionally disabled: we want to see the spectrum, not consistency.",
    })
    print(f"\nAll outputs in {run_dir}")


if __name__ == "__main__":
    main()
