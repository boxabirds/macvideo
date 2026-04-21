#!/usr/bin/env python
"""POC 13 prep — two-pass LLM + identity-chained Gemini keyframes for 3 lyric lines.

Pass A: full lyrics + filter → persistent character/world brief (once per song).
Pass B: each target line + brief + filter → contextual image prompt (3 calls).
Gemini image gen: shot 1 unconditioned; shots 2 & 3 include prior keyframes as
reference (identity chain, POC 6 pattern).

All prompts saved to prompts.json in a timestamped run dir.
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


ALIGNED_PATH = REPO_ROOT / "pocs" / "07-whisperx" / "outputs" / "aligned.json"
LYRICS_PATH = REPO_ROOT / "music" / "my-little-blackbird.txt"

LLM_MODEL = "gemini-3-flash-preview"
IMG_MODEL = "gemini-3.1-flash-image-preview"
FPS = 24

FILTER_WORD = "charcoal"

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
this song must honour. Describe:
 - The narrator: appearance, age, clothing, demeanour (specific visual cues only)
 - The central metaphorical subject as a visible entity (here: the blackbird)
 - The primary setting / world (domestic? exterior? atmospheric qualities)
 - How the "{filter_word}" style manifests on all of the above (materials,
   textures, line quality, palette, lighting)

Use concrete visual language only — no emotional labels. This brief is the
anchor for per-line shot prompts: later prompts should reference THIS
description verbatim rather than inventing new characters or worlds.

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

Write ONE image-generation prompt (3-4 sentences) for a keyframe representing
this line in the context of the full song. The image must:
 1. Contain the same character/world/style described in the brief above —
    reference it rather than invent afresh.
 2. Stage the moment that the target line expresses (its metaphor, not just
    its surface meaning).
 3. Use only concrete visual cues — materials, textures, lighting, palette,
    composition. No emotional labels, no "in the style of".

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


def main():
    run_dir = make_run_dir(__file__, tag=FILTER_WORD)
    print(f"Run dir: {run_dir}")

    aligned = json.loads(ALIGNED_PATH.read_text())
    lyrics_text = clean_lyrics_for_llm(LYRICS_PATH.read_text())

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # Pass A — character/world brief
    print("\n=== Pass A: character & world brief ===")
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

    # First pass: collect timings for all lines so we can compute gap-inclusive durations.
    # Each clip's VIDEO spans [line[i].start, line[i+1].start] (or line.end for last line)
    # so cuts happen at lyric boundaries while one continuous audio slice plays underneath.
    line_timings = []
    for idx, target in enumerate(TARGET_LINES, start=1):
        line_words = find_line_words(aligned, target)
        if line_words is None:
            print(f"ERROR: could not locate {target!r} in aligned.json", file=sys.stderr)
            sys.exit(3)
        line_timings.append({
            "index": idx,
            "target_text": target,
            "start_t": float(line_words[0]["start"]),
            "end_t": float(line_words[-1]["end"]),
        })

    n = len(line_timings)
    audio_span_start = line_timings[0]["start_t"]
    audio_span_end = line_timings[-1]["end_t"]
    print(f"\nContinuous audio span: {audio_span_start:.3f}–{audio_span_end:.3f} s "
          f"({audio_span_end - audio_span_start:.3f} s)")

    lines_info = []
    for i, lt in enumerate(line_timings):
        if i < n - 1:
            clip_end = line_timings[i + 1]["start_t"]
        else:
            clip_end = lt["end_t"]
        clip_duration = clip_end - lt["start_t"]
        raw_frames = round(clip_duration * FPS)
        num_frames = round_to_frame_constraint(raw_frames)
        lines_info.append({
            "index": lt["index"],
            "target_text": lt["target_text"],
            "line_start_t": round(lt["start_t"], 3),
            "line_end_t": round(lt["end_t"], 3),
            "line_duration_s": round(lt["end_t"] - lt["start_t"], 3),
            "clip_start_t": round(lt["start_t"], 3),
            "clip_end_t": round(clip_end, 3),
            "clip_duration_s": round(clip_duration, 3),
            "num_frames": num_frames,
            "actual_clip_duration_s": round(num_frames / FPS, 3),
        })

    image_prompts = []
    pass_b_inputs = []
    reference_bytes: list[bytes] = []
    keyframe_latencies = []

    for info in lines_info:
        idx = info["index"]
        target = info["target_text"]
        print(f"\n=== Line {idx}: {target!r} ===")
        print(f"  line {info['line_start_t']:.3f}–{info['line_end_t']:.3f} s")
        print(f"  clip (gap-inclusive) {info['clip_duration_s']:.3f} s → {info['num_frames']} frames")

        pass_b_input = PASS_B_PROMPT.format(
            lyrics=lyrics_text, brief=brief, target_line=target
        )
        pass_b_inputs.append(pass_b_input)
        t0 = time.time()
        resp_b = client.models.generate_content(model=LLM_MODEL, contents=pass_b_input)
        dt_b = time.time() - t0
        image_prompt = resp_b.text.strip().strip('"').strip()
        image_prompts.append(image_prompt)
        print(f"  prompt ({dt_b:.2f} s): {image_prompt[:180]}{'...' if len(image_prompt) > 180 else ''}")

        # Image gen with identity chain — prior keyframes as reference
        contents: list = []
        for prior in reference_bytes:
            contents.append(types.Part.from_bytes(data=prior, mime_type="image/png"))
        contents.append(image_prompt)

        t0 = time.time()
        img_resp = client.models.generate_content(model=IMG_MODEL, contents=contents)
        img_dt = time.time() - t0
        keyframe_latencies.append(img_dt)

        image_bytes = None
        for part in img_resp.candidates[0].content.parts:
            if getattr(part, "inline_data", None) is not None:
                image_bytes = part.inline_data.data
                break
        if image_bytes is None:
            print(f"  ERROR: no image returned for line {idx}", file=sys.stderr)
            sys.exit(4)

        keyframe_path = run_dir / f"keyframe_{idx:02d}.png"
        keyframe_path.write_bytes(image_bytes)
        reference_bytes.append(image_bytes)
        print(f"  keyframe saved ({img_dt:.2f} s, {len(image_bytes):,} bytes): {keyframe_path.name}")

    # Persist everything
    (run_dir / "lines.json").write_text(json.dumps(lines_info, indent=2))
    (run_dir / "audio_span.json").write_text(json.dumps({
        "start_t": round(audio_span_start, 3),
        "end_t": round(audio_span_end, 3),
        "duration_s": round(audio_span_end - audio_span_start, 3),
    }, indent=2))

    save_prompts(run_dir, {
        "filter": FILTER_WORD,
        "llm_model": LLM_MODEL,
        "img_model": IMG_MODEL,
        "target_lines": TARGET_LINES,
        "pass_a_input": PASS_A_PROMPT,
        "pass_a_output_brief": brief,
        "pass_b_input_template": PASS_B_PROMPT,
        "pass_b_inputs_per_line": pass_b_inputs,
        "image_prompts_per_line": image_prompts,
        "keyframe_latencies_s": [round(x, 2) for x in keyframe_latencies],
        "brief_latency_s": round(brief_dt, 2),
    })
    print(f"\nprompts.json + character_brief.json + lines.json written to {run_dir}")


if __name__ == "__main__":
    main()
