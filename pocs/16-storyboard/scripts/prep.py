#!/usr/bin/env python
"""POC 16 prep — Pass A (world) + Pass C (storyboard) + Pass B (per-shot image prompt)
+ Gemini identity-chained keyframes.

Fixes two problems from POC 15:
  1. Camera arc is now planned across the sequence (Pass C), not improvised per shot.
  2. Per-shot image prompts get narrative beat + prev/next links, so adjacent
     shots progress rather than repeat — even when target lines are identical
     (the pathological test case).
"""

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
from google.genai import types

LYRICS_PATH = REPO_ROOT / "music" / "my-little-blackbird.txt"
LLM_MODEL = "gemini-3-flash-preview"
IMG_MODEL = "gemini-3.1-flash-image-preview"
FPS = 24
FILTER_WORD = "charcoal"

# PATHOLOGICAL TEST: three identical lines. If Pass C works, the three
# keyframes should progress through the moment, not clone each other.
TARGET_LINES = [
    "He's arrived again",
    "He's arrived again",
    "He's arrived again",
]
# Baseline (for comparison): uncomment to switch
# TARGET_LINES = [
#     "He's arrived again",
#     "Whispering in my ear",
#     "That's my little blackbird",
# ]

RUN_TAG = "pathological" if len(set(TARGET_LINES)) == 1 else "baseline"

# Fixed 2 s per shot for the pathological case (no real song timing applies)
FIXED_SHOT_DURATION_S = 2.0

CAMERA_INTENTS = [
    "static hold",
    "slow push in",
    "slow pull back",
    "pan left",
    "pan right",
    "tilt up",
    "tilt down",
    "orbit left",
    "orbit right",
    "handheld drift",
    "held on detail",
]

PASS_A_PROMPT = """You are a music video director. Read the song carefully.

Song lyrics:
---
{lyrics}
---

The video will be rendered in the "{filter_word}" style.

Write a short "character & world brief" (5-8 sentences) that every shot of
this song must honour. Describe the narrator, the central metaphorical
subject (here: the blackbird), the primary setting, and how the
"{filter_word}" style manifests on all of them (materials, textures, line
quality, palette, lighting).

Use concrete visual language only. Describe what IS present, never what is
absent.

Return ONLY the brief as a single paragraph."""

PASS_C_PROMPT = """You are a music video director AND a storyboard artist.

World brief (applies to every shot):
---
{brief}
---

You are given {n} shots to storyboard as a SEQUENCE. Each target line is
below in order. Your job is to plan the sequence so that adjacent shots
progress narratively and the camera arc feels coherent.

CRITICAL:
  - If two or more target lines are identical, you MUST still give them
    distinct beats that PROGRESS the moment (establish → develop → culminate).
    Do not let identical lines produce identical beats.
  - Camera direction should not reverse on adjacent shots unless the
    sequence intentionally punctuates.
  - Use ONLY these exact values for camera_intent:
    {camera_intents}

For each shot, produce:
  - index              (1-based)
  - target_text        (echo the input target line)
  - beat               (one concrete sentence: the narrative moment this shot captures)
  - camera_intent      (from the allowed vocabulary)
  - subject_focus      (what the frame centres on — a concrete element)
  - prev_link          (one sentence connecting back to prior shot; null for shot 1)
  - next_link          (one sentence setting up the next shot; null for last)

Also produce "sequence_arc" — one sentence describing the camera trajectory
across the full sequence.

Target shots (in order):
{targets_block}

Return a SINGLE JSON object with exactly this structure:
{{
  "sequence_arc": "...",
  "shots": [
    {{"index": 1, "target_text": "...", "beat": "...", "camera_intent": "...",
      "subject_focus": "...", "prev_link": null, "next_link": "..."}},
    ...
  ]
}}

Return ONLY the JSON, no preamble, no code fences."""

PASS_B_PROMPT = """You are a music video director generating ONE image prompt for a keyframe.

World brief (applies to every shot):
---
{brief}
---

Storyboard for this specific shot:
  - target line:       "{target_text}"
  - narrative beat:    {beat}
  - subject focus:     {subject_focus}
  - camera intent:     {camera_intent}
  - connects from prior shot: {prev_link}
  - sets up next shot:        {next_link}

Write ONE image-generation prompt (3-4 sentences) for the keyframe. The image must:
  - Depict the beat (not just the literal surface of the target line)
  - Centre on the subject_focus
  - Honour the world brief (same character, same setting, same filter)
  - Describe only what IS present in the frame — materials, objects, atmosphere, motion
  - Use concrete visual cues only — no emotional labels, no negations

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


def round_to_frame_constraint(n_frames: int) -> int:
    if n_frames < 1:
        return 1
    return ((n_frames - 1) // 8) * 8 + 1


def main():
    run_dir = make_run_dir(__file__, tag=f"{FILTER_WORD}-{RUN_TAG}")
    print(f"Run dir: {run_dir}")
    print(f"Test mode: {RUN_TAG.upper()}")
    print(f"Target lines: {TARGET_LINES}")

    lyrics_text = clean_lyrics_for_llm(LYRICS_PATH.read_text())
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # Pass A — world brief
    print("\n=== Pass A: world brief ===")
    pass_a_input = PASS_A_PROMPT.format(lyrics=lyrics_text, filter_word=FILTER_WORD)
    t0 = time.time()
    brief_resp = client.models.generate_content(model=LLM_MODEL, contents=pass_a_input)
    brief_dt = time.time() - t0
    brief = brief_resp.text.strip()
    print(f"  {brief_dt:.2f} s — {brief[:180]}{'...' if len(brief) > 180 else ''}")
    (run_dir / "character_brief.json").write_text(
        json.dumps({"filter": FILTER_WORD, "brief": brief, "latency_s": round(brief_dt, 2)}, indent=2)
    )

    # Pass C — storyboard
    print("\n=== Pass C: storyboard ===")
    targets_block = "\n".join(
        f"  Shot {i+1}: {t!r}" for i, t in enumerate(TARGET_LINES)
    )
    pass_c_input = PASS_C_PROMPT.format(
        brief=brief,
        n=len(TARGET_LINES),
        camera_intents=", ".join(CAMERA_INTENTS),
        targets_block=targets_block,
    )
    t0 = time.time()
    storyboard_resp = client.models.generate_content(
        model=LLM_MODEL,
        contents=pass_c_input,
        config={"response_mime_type": "application/json"},
    )
    storyboard_dt = time.time() - t0
    storyboard_raw = storyboard_resp.text.strip()
    try:
        storyboard = json.loads(storyboard_raw)
    except json.JSONDecodeError as e:
        print(f"  ERROR: storyboard is not valid JSON: {e}", file=sys.stderr)
        print(f"  Raw output:\n{storyboard_raw}", file=sys.stderr)
        sys.exit(3)
    print(f"  {storyboard_dt:.2f} s")
    print(f"  sequence_arc: {storyboard.get('sequence_arc')}")
    for s in storyboard.get("shots", []):
        print(f"  Shot {s['index']}: camera={s['camera_intent']!r}, "
              f"focus={s['subject_focus']!r}")
        print(f"    beat: {s['beat']}")
        if s.get("prev_link"):
            print(f"    prev_link: {s['prev_link']}")
        if s.get("next_link"):
            print(f"    next_link: {s['next_link']}")

    (run_dir / "storyboard.json").write_text(json.dumps(storyboard, indent=2))

    # Pass B — per-shot image prompts + Gemini keyframe with identity chain
    shots = []
    pass_b_inputs = {}
    image_prompts = {}
    reference_bytes: list[bytes] = []

    for i, (target, sb) in enumerate(zip(TARGET_LINES, storyboard["shots"])):
        idx = i + 1
        print(f"\n=== Shot {idx} (target: {target!r}) ===")
        pass_b_input = PASS_B_PROMPT.format(
            brief=brief,
            target_text=target,
            beat=sb["beat"],
            subject_focus=sb["subject_focus"],
            camera_intent=sb["camera_intent"],
            prev_link=sb.get("prev_link") or "null",
            next_link=sb.get("next_link") or "null",
        )
        pass_b_inputs[f"shot_{idx:02d}"] = pass_b_input

        t0 = time.time()
        resp = client.models.generate_content(model=LLM_MODEL, contents=pass_b_input)
        pass_b_dt = time.time() - t0
        image_prompt = resp.text.strip().strip('"').strip()
        image_prompts[f"shot_{idx:02d}"] = image_prompt
        print(f"  image prompt ({pass_b_dt:.2f} s): "
              f"{image_prompt[:180]}{'...' if len(image_prompt) > 180 else ''}")

        # Identity chain — prior keyframes as reference
        contents: list = []
        for prior in reference_bytes:
            contents.append(types.Part.from_bytes(data=prior, mime_type="image/png"))
        contents.append(image_prompt)

        # Gemini image preview occasionally returns empty responses (safety
        # filter, API hiccup). Retry a few times before giving up.
        image_bytes = None
        img_dt = 0.0
        MAX_ATTEMPTS = 3
        for attempt in range(1, MAX_ATTEMPTS + 1):
            t0 = time.time()
            try:
                img_resp = client.models.generate_content(model=IMG_MODEL, contents=contents)
            except Exception as e:
                print(f"  attempt {attempt}/{MAX_ATTEMPTS} exception: {e}", file=sys.stderr)
                time.sleep(2)
                continue
            img_dt = time.time() - t0

            candidates = getattr(img_resp, "candidates", None) or []
            if not candidates:
                print(f"  attempt {attempt}/{MAX_ATTEMPTS}: no candidates "
                      f"(prompt_feedback={getattr(img_resp, 'prompt_feedback', None)})",
                      file=sys.stderr)
                time.sleep(2)
                continue

            cand = candidates[0]
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) if content else None
            if not parts:
                print(f"  attempt {attempt}/{MAX_ATTEMPTS}: empty parts "
                      f"(finish_reason={getattr(cand, 'finish_reason', None)})",
                      file=sys.stderr)
                time.sleep(2)
                continue

            for part in parts:
                if getattr(part, "inline_data", None) is not None:
                    image_bytes = part.inline_data.data
                    break
            if image_bytes is not None:
                break
            print(f"  attempt {attempt}/{MAX_ATTEMPTS}: no inline_data in parts", file=sys.stderr)
            time.sleep(2)

        if image_bytes is None:
            print(f"  ERROR: no image after {MAX_ATTEMPTS} attempts for shot {idx}", file=sys.stderr)
            sys.exit(4)

        keyframe_path = run_dir / f"keyframe_{idx:02d}.png"
        keyframe_path.write_bytes(image_bytes)
        reference_bytes.append(image_bytes)
        print(f"  keyframe saved ({img_dt:.2f} s): {keyframe_path.name}")

        raw_frames = round(FIXED_SHOT_DURATION_S * FPS)
        num_frames = round_to_frame_constraint(raw_frames)
        shots.append({
            "index": idx,
            "target_text": target,
            "beat": sb["beat"],
            "camera_intent": sb["camera_intent"],
            "subject_focus": sb["subject_focus"],
            "prev_link": sb.get("prev_link"),
            "next_link": sb.get("next_link"),
            "image_prompt": image_prompt,
            "duration_s": FIXED_SHOT_DURATION_S,
            "num_frames": num_frames,
            "actual_clip_duration_s": round(num_frames / FPS, 3),
        })

    (run_dir / "shots.json").write_text(json.dumps(shots, indent=2))

    save_prompts(run_dir, {
        "filter": FILTER_WORD,
        "run_tag": RUN_TAG,
        "target_lines": TARGET_LINES,
        "camera_intents_vocabulary": CAMERA_INTENTS,
        "llm_model": LLM_MODEL,
        "img_model": IMG_MODEL,
        "pass_a_input": PASS_A_PROMPT,
        "pass_a_output_brief": brief,
        "pass_c_input": pass_c_input,
        "pass_c_output_storyboard": storyboard,
        "pass_b_input_template": PASS_B_PROMPT,
        "pass_b_inputs_per_shot": pass_b_inputs,
        "image_prompts_per_shot": image_prompts,
        "sequence_arc": storyboard.get("sequence_arc"),
    })
    print(f"\nprompts.json + storyboard.json + shots.json + {len(shots)} keyframes in {run_dir}")


if __name__ == "__main__":
    main()
