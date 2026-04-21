#!/usr/bin/env python
"""POC 12 prep — pick a lyric line, ask an LLM for a CONTEXT-AWARE image prompt,
then generate the Gemini keyframe.

v2 (this version): the LLM reads the full song lyrics and the target line,
then writes an image prompt that represents the line in the context of the
whole song — not a literal surface reading. This is the Deforum-style trick
the user validated years ago, now ported to the new pipeline.
"""

import json
import os
import re
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


ALIGNED_PATH = REPO_ROOT / "pocs" / "07-whisperx" / "outputs" / "aligned.json"
LYRICS_PATH = REPO_ROOT / "music" / "my-little-blackbird.txt"
TARGET_LINE_TEXT = "That's my little blackbird"

LLM_MODEL = "gemini-3-flash-preview"
IMG_MODEL = "gemini-3.1-flash-image-preview"
FPS = 24

# Neutral base — we want to judge whether the LLM gets the METAPHOR right,
# not whether a particular filter lands. Style variation tested separately in POC 10.
STYLE_BASE = (
    "cinematic, natural soft light, shallow depth of field, 16mm film grain, no text"
)

CONTEXT_PROMPT_TEMPLATE = """You are a music video director generating keyframe image prompts for a song.

Full lyrics:
---
{lyrics}
---

Target line to illustrate: "{target_line}"

Write ONE image prompt (3-4 sentences) for a keyframe that represents this
line IN THE CONTEXT of the whole song. Consider the song's central metaphor,
the narrator's relationship to the subject, and the emotional tone the line
sits within. If the song makes the line metaphorical, the keyframe should
reflect the metaphor — not the literal surface reading.

Append this style base verbatim to your prompt: {style_base}

Return ONLY the final image prompt as a single paragraph. No preamble, no
quotes, no explanations."""


SECTION_MARKER_RE = re.compile(r"^\*+\[[^\]]*\]\*+\s*$")


def clean_lyrics_for_llm(raw: str) -> str:
    """Strip markdown but keep line breaks and section labels (the LLM benefits from structure)."""
    out_lines = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        # Keep section markers for structural context — they help the LLM see form
        out_lines.append(s)
    return "\n".join(out_lines).strip()


def find_line_words(aligned, target_text: str):
    """Return the contiguous word list whose concatenation matches target_text."""
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
    """Round to nearest m where m == 1 + 8*k, m >= 1."""
    if n_frames < 1:
        return 1
    return ((n_frames - 1) // 8) * 8 + 1


def main():
    if not ALIGNED_PATH.exists():
        print(f"ERROR: {ALIGNED_PATH} missing. Run POC 7 first.", file=sys.stderr)
        sys.exit(2)
    if not LYRICS_PATH.exists():
        print(f"ERROR: {LYRICS_PATH} missing.", file=sys.stderr)
        sys.exit(2)

    aligned = json.loads(ALIGNED_PATH.read_text())
    line_words = find_line_words(aligned, TARGET_LINE_TEXT)
    if line_words is None:
        print(f"ERROR: could not locate {TARGET_LINE_TEXT!r} in aligned.json", file=sys.stderr)
        sys.exit(3)

    start_t = float(line_words[0]["start"])
    end_t = float(line_words[-1]["end"])
    duration_s = end_t - start_t
    raw_frames = round(duration_s * FPS)
    num_frames = round_to_frame_constraint(raw_frames)

    line_info = {
        "target_text": TARGET_LINE_TEXT,
        "matched_words": [w["word"] for w in line_words],
        "start_t": round(start_t, 3),
        "end_t": round(end_t, 3),
        "duration_s": round(duration_s, 3),
        "fps": FPS,
        "raw_frames": raw_frames,
        "num_frames": num_frames,
        "actual_clip_duration_s": round(num_frames / FPS, 3),
    }
    (OUT_DIR / "line.json").write_text(json.dumps(line_info, indent=2))
    print(f"Line: {TARGET_LINE_TEXT!r}")
    print(f"  {line_info['start_t']:.3f} s → {line_info['end_t']:.3f} s "
          f"(duration {line_info['duration_s']:.3f} s)")
    print(f"  num_frames: {num_frames} ({line_info['actual_clip_duration_s']:.3f} s)")

    lyrics_text = clean_lyrics_for_llm(LYRICS_PATH.read_text())

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    print(f"\n=== Context-aware image prompt (via {LLM_MODEL}) ===")
    llm_prompt = CONTEXT_PROMPT_TEMPLATE.format(
        lyrics=lyrics_text,
        target_line=TARGET_LINE_TEXT,
        style_base=STYLE_BASE,
    )
    t0 = time.time()
    llm_response = client.models.generate_content(
        model=LLM_MODEL,
        contents=llm_prompt,
    )
    llm_dt = time.time() - t0
    image_prompt = llm_response.text.strip().strip('"').strip()
    print(f"  {llm_dt:.2f} s")
    print(f"  prompt: {image_prompt}")

    print(f"\n=== Rendering keyframe via {IMG_MODEL} ===")
    t0 = time.time()
    img_response = client.models.generate_content(
        model=IMG_MODEL,
        contents=image_prompt,
    )
    img_dt = time.time() - t0

    out = OUT_DIR / "keyframe.png"
    saved = False
    for part in img_response.candidates[0].content.parts:
        if getattr(part, "inline_data", None) is not None:
            out.write_bytes(part.inline_data.data)
            saved = True
            break

    if not saved:
        print("ERROR: no image returned", file=sys.stderr)
        sys.exit(4)

    print(f"  saved {out} in {img_dt:.2f} s ({out.stat().st_size:,} bytes)")

    meta = {
        "llm_model": LLM_MODEL,
        "image_model": IMG_MODEL,
        "target_line": TARGET_LINE_TEXT,
        "style_base": STYLE_BASE,
        "llm_input_prompt": llm_prompt,
        "image_prompt": image_prompt,
        "llm_latency_s": round(llm_dt, 2),
        "image_latency_s": round(img_dt, 2),
        "llm_usage": llm_response.usage_metadata.model_dump() if getattr(llm_response, "usage_metadata", None) else None,
        "image_usage": img_response.usage_metadata.model_dump() if getattr(img_response, "usage_metadata", None) else None,
    }
    (OUT_DIR / "keyframe_meta.json").write_text(json.dumps(meta, indent=2, default=str))


if __name__ == "__main__":
    main()
