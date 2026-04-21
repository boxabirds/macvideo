#!/usr/bin/env python
"""POC 15 prep — lyric shots + interpolated gap shots, all identity-chained."""

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


ALIGNED_PATH = REPO_ROOT / "pocs" / "07-whisperx" / "outputs" / "aligned.json"
LYRICS_PATH = REPO_ROOT / "music" / "my-little-blackbird.txt"

LLM_MODEL = "gemini-3-flash-preview"
IMG_MODEL = "gemini-3.1-flash-image-preview"
FPS = 24

FILTER_WORD = "charcoal"
GAP_THRESHOLD_S = 1.5

TARGET_LINES = [
    "He's arrived again",
    "Whispering in my ear",
    "That's my little blackbird",
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
absent. This brief is the anchor for per-shot prompts.

Return ONLY the brief as a single paragraph."""

PASS_B_LYRIC_PROMPT = """You are a music video director generating one keyframe image prompt for a sung line.

Song lyrics:
---
{lyrics}
---

Persistent character & world brief:
---
{brief}
---

Target line for this shot: "{target_line}"

Write ONE image-generation prompt (3-4 sentences) for a keyframe representing
this line in context of the full song. Describe what IS present in the frame
— materials, objects, atmosphere, motion. Honour the world brief; do not
invent new characters or settings. Use concrete visual cues only.

Return ONLY the final image prompt as a single paragraph."""

PASS_B_GAP_PROMPT = """You are a music video director generating one keyframe image prompt for an instrumental moment between two sung lines.

Song lyrics (for context):
---
{lyrics}
---

Persistent character & world brief:
---
{brief}
---

This shot is the INSTRUMENTAL moment between these two sung shots:

PREVIOUS shot's image prompt:
---
{prev_prompt}
---

NEXT shot's image prompt:
---
{next_prompt}
---

Write ONE image-generation prompt (3-4 sentences) for a keyframe that fits
NATURALLY between the previous and next shots. It should honour the world
brief (same character, same setting, same filter). Describe a transitional
moment: a held look, a shift in the bird's position, a change in light, a
continuation of the previous shot's motion — whatever reads as the quiet
bridge between what was just sung and what will be sung next. Describe only
what IS present.

Return ONLY the final image prompt as a single paragraph."""


SECTION_MARKER_RE = re.compile(r"^\*+\[[^\]]*\]\*+\s*$")


def clean_lyrics_for_llm(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        lines.append(s)
    return "\n".join(lines).strip()


def find_line_words(aligned, target_text: str):
    target_tokens = target_text.replace("'", "").replace(",", "").lower().split()
    words = aligned["words"]
    for i in range(len(words) - len(target_tokens) + 1):
        window = [
            "".join(ch for ch in w["word"].lower() if ch.isalnum() or ch == "'").replace("'", "")
            for w in words[i : i + len(target_tokens)]
        ]
        clean_target = ["".join(ch for ch in t if ch.isalnum()) for t in target_tokens]
        if window == clean_target:
            return words[i : i + len(target_tokens)]
    return None


def round_to_frame_constraint(n_frames: int) -> int:
    if n_frames < 1:
        return 1
    return ((n_frames - 1) // 8) * 8 + 1


def build_shot_sequence(line_timings):
    """Interleave lyric shots with gap shots where gaps exceed threshold.

    Returns: list of shot dicts with keys: type ('line'|'gap'),
    target_text, start_t, end_t, duration_s, plus (for gaps) prev/next line refs.
    """
    shots = []
    n = len(line_timings)
    for i, lt in enumerate(line_timings):
        shots.append({
            "type": "line",
            "target_text": lt["target_text"],
            "start_t": lt["start_t"],
            "end_t": lt["end_t"],
            "duration_s": lt["end_t"] - lt["start_t"],
        })
        if i < n - 1:
            gap = line_timings[i + 1]["start_t"] - lt["end_t"]
            if gap >= GAP_THRESHOLD_S:
                shots.append({
                    "type": "gap",
                    "target_text": None,
                    "start_t": lt["end_t"],
                    "end_t": line_timings[i + 1]["start_t"],
                    "duration_s": gap,
                    "prev_line_text": lt["target_text"],
                    "next_line_text": line_timings[i + 1]["target_text"],
                })
    return shots


def main():
    run_dir = make_run_dir(__file__, tag=FILTER_WORD)
    print(f"Run dir: {run_dir}")

    aligned = json.loads(ALIGNED_PATH.read_text())
    lyrics_text = clean_lyrics_for_llm(LYRICS_PATH.read_text())

    # Resolve line timings
    line_timings = []
    for target in TARGET_LINES:
        words = find_line_words(aligned, target)
        if words is None:
            print(f"ERROR: cannot locate {target!r}", file=sys.stderr)
            sys.exit(3)
        line_timings.append({
            "target_text": target,
            "start_t": float(words[0]["start"]),
            "end_t": float(words[-1]["end"]),
        })

    shots = build_shot_sequence(line_timings)
    audio_span_start = shots[0]["start_t"]
    audio_span_end = shots[-1]["end_t"]
    print(f"Sequence: {len(shots)} shots "
          f"({sum(1 for s in shots if s['type']=='line')} lyric, "
          f"{sum(1 for s in shots if s['type']=='gap')} gap)")
    print(f"Audio span: {audio_span_start:.3f}–{audio_span_end:.3f} s")

    # Assign frame counts — clips span exactly their shot window
    for s in shots:
        raw_frames = round(s["duration_s"] * FPS)
        s["num_frames"] = round_to_frame_constraint(raw_frames)
        s["actual_clip_duration_s"] = round(s["num_frames"] / FPS, 3)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # Pass A
    print("\n=== Pass A: world brief ===")
    pass_a_input = PASS_A_PROMPT.format(lyrics=lyrics_text, filter_word=FILTER_WORD)
    t0 = time.time()
    brief_resp = client.models.generate_content(model=LLM_MODEL, contents=pass_a_input)
    brief_dt = time.time() - t0
    brief = brief_resp.text.strip()
    print(f"  {brief_dt:.2f} s")
    print(f"  brief: {brief[:200]}{'...' if len(brief) > 200 else ''}")
    (run_dir / "character_brief.json").write_text(
        json.dumps({"filter": FILTER_WORD, "brief": brief, "latency_s": round(brief_dt, 2)}, indent=2)
    )

    # First pass: generate LYRIC prompts only (so we have prev/next text when
    # synthesising gap prompts). Then a second pass for gap prompts. Then
    # image gen in sequence order, with identity chain.
    lyric_prompts = {}
    pass_b_inputs = {}
    for i, shot in enumerate(shots):
        if shot["type"] != "line":
            continue
        pass_b_input = PASS_B_LYRIC_PROMPT.format(
            lyrics=lyrics_text, brief=brief, target_line=shot["target_text"]
        )
        pass_b_inputs[f"shot_{i+1:02d}"] = pass_b_input
        t0 = time.time()
        resp = client.models.generate_content(model=LLM_MODEL, contents=pass_b_input)
        dt = time.time() - t0
        prompt_text = resp.text.strip().strip('"').strip()
        lyric_prompts[i] = prompt_text
        shot["image_prompt"] = prompt_text
        shot["pass_b_latency_s"] = round(dt, 2)
        print(f"\n=== Shot {i+1} (LINE: {shot['target_text']!r}) ===")
        print(f"  prompt ({dt:.2f} s): {prompt_text[:180]}{'...' if len(prompt_text) > 180 else ''}")

    # Pass for gap prompts — each needs prev and next lyric prompts
    for i, shot in enumerate(shots):
        if shot["type"] != "gap":
            continue
        prev_prompt = lyric_prompts[i - 1]
        next_prompt = lyric_prompts[i + 1]
        pass_b_input = PASS_B_GAP_PROMPT.format(
            lyrics=lyrics_text, brief=brief,
            prev_prompt=prev_prompt, next_prompt=next_prompt,
        )
        pass_b_inputs[f"shot_{i+1:02d}"] = pass_b_input
        t0 = time.time()
        resp = client.models.generate_content(model=LLM_MODEL, contents=pass_b_input)
        dt = time.time() - t0
        prompt_text = resp.text.strip().strip('"').strip()
        shot["image_prompt"] = prompt_text
        shot["pass_b_latency_s"] = round(dt, 2)
        print(f"\n=== Shot {i+1} (GAP {shot['prev_line_text']!r} → {shot['next_line_text']!r}) ===")
        print(f"  prompt ({dt:.2f} s): {prompt_text[:180]}{'...' if len(prompt_text) > 180 else ''}")

    # Image gen in sequence, identity-chained
    reference_bytes: list[bytes] = []
    for i, shot in enumerate(shots):
        slot = f"keyframe_{i+1:02d}.png"
        contents: list = []
        for prior in reference_bytes:
            contents.append(types.Part.from_bytes(data=prior, mime_type="image/png"))
        contents.append(shot["image_prompt"])

        t0 = time.time()
        img_resp = client.models.generate_content(model=IMG_MODEL, contents=contents)
        dt = time.time() - t0

        image_bytes = None
        for part in img_resp.candidates[0].content.parts:
            if getattr(part, "inline_data", None) is not None:
                image_bytes = part.inline_data.data
                break
        if image_bytes is None:
            print(f"ERROR: no image returned for shot {i+1}", file=sys.stderr)
            sys.exit(4)

        (run_dir / slot).write_bytes(image_bytes)
        reference_bytes.append(image_bytes)
        shot["keyframe_file"] = slot
        shot["keyframe_latency_s"] = round(dt, 2)
        print(f"  shot {i+1} keyframe saved ({dt:.2f} s, {len(image_bytes):,} bytes)")

    # Persist shot sequence + audio span
    (run_dir / "shots.json").write_text(json.dumps(shots, indent=2, default=str))
    (run_dir / "audio_span.json").write_text(json.dumps({
        "start_t": round(audio_span_start, 3),
        "end_t": round(audio_span_end, 3),
        "duration_s": round(audio_span_end - audio_span_start, 3),
    }, indent=2))

    save_prompts(run_dir, {
        "filter": FILTER_WORD,
        "gap_threshold_s": GAP_THRESHOLD_S,
        "llm_model": LLM_MODEL,
        "img_model": IMG_MODEL,
        "target_lines": TARGET_LINES,
        "pass_a_input": PASS_A_PROMPT,
        "pass_a_output_brief": brief,
        "pass_b_lyric_template": PASS_B_LYRIC_PROMPT,
        "pass_b_gap_template": PASS_B_GAP_PROMPT,
        "pass_b_inputs_per_shot": pass_b_inputs,
        "image_prompts_per_shot": {
            f"shot_{i+1:02d}": s["image_prompt"] for i, s in enumerate(shots)
        },
        "shot_sequence": [
            {"index": i + 1, "type": s["type"], "target_text": s.get("target_text"),
             "duration_s": s["duration_s"], "num_frames": s["num_frames"]}
            for i, s in enumerate(shots)
        ],
    })
    print(f"\nprompts.json + shots.json + audio_span.json + {len(shots)} keyframes in {run_dir}")


if __name__ == "__main__":
    main()
