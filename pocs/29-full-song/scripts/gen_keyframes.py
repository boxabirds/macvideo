"""Run Pass A (world brief), Pass C (storyboard), Pass B (per-shot image prompt)
and generate Gemini keyframes with identity chain.

Resumable — if a keyframe already exists, skips to next shot. If character_brief
or storyboard exists, reuses.
"""

from __future__ import annotations

import argparse
import json
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

LLM_MODEL = "gemini-3-flash-preview"
IMG_MODEL = "gemini-3.1-flash-image-preview"
# imageConfig.aspectRatio forces 16:9 landscape so Gemini doesn't drift into
# portrait on vertical-composition prompts (papercut dioramas, tall figures).
IMG_CONFIG = {
    "response_modalities": ["IMAGE", "TEXT"],
    "image_config": {"aspect_ratio": "16:9", "image_size": "1K"},
}

ABSTRACTION_DESCRIPTORS = {
    0: "fully representational, photographic clarity, subjects rendered as concrete recognisable form with grounded proportions and depth",
    25: "loosely expressive — brushwork and line quality given primacy over accuracy; subjects still clearly legible but simplified; distortion and gesture honoured",
    50: "heavily stylised — figures become simplified masses and volumes, architecture reduced to structural shapes; recognisable but abstracted",
    75: "predominantly abstract — the figure becomes a dark mass or smear, the setting becomes rectangles of light and shadow, details replaced by rhythm and weight",
    100: "pure abstraction — no recognisable figures, objects, or settings; composition is colour field, line, rhythm, texture",
}

CAMERA_INTENTS = [
    "static hold", "slow push in", "slow pull back",
    "pan left", "pan right", "tilt up", "tilt down",
    "orbit left", "orbit right", "handheld drift", "held on detail",
]

IDENTITY_REF_WINDOW = 4  # keep last N keyframes as identity references

PASS_A_PROMPT = """You are a music video director. Read the song carefully.

Song lyrics:
---
{lyrics}
---

The video will be rendered in the "{filter_word}" style.
Abstraction level: {abstraction}/100. Apply throughout: {abstraction_descriptor}

Write a short "character & world brief" (5-8 sentences) that every shot of
this song must honour. Describe:
 - The narrator: appearance, clothing, demeanour (concrete visual cues only)
 - The central metaphorical subject of this song as a visible entity
 - The primary setting / world (domestic? exterior? atmospheric qualities)
 - How the "{filter_word}" style manifests on all of the above (materials,
   textures, line quality, palette, lighting)

Use concrete visual language only — no emotional labels. Describe what IS
present, never what is absent.

Return ONLY the brief, as a single paragraph. No preamble, no quotes."""

PASS_C_PROMPT = """You are a music video director AND a storyboard artist.

World brief (applies to every shot):
---
{brief}
---

You are given {n} shots to storyboard as a SEQUENCE for a full music video.
Each shot's target text is below in order; some are lyric lines, some are
instrumental fillers ([instrumental intro], [instrumental bridge], etc.).

CRITICAL:
  - Plan the sequence so adjacent shots progress narratively.
  - Instrumental fillers should evoke the song's atmosphere, NOT narrate.
  - Camera direction should not reverse on adjacent shots unless punctuated.
  - Use ONLY these exact values for camera_intent:
    {camera_intents}
  - Never let two adjacent shots produce identical beats, even if identical
    target text appears (establish → develop → culminate progression).

For each shot, produce:
  - index              (1-based)
  - target_text        (echo input)
  - beat               (one concrete sentence: the narrative moment this shot captures)
  - camera_intent      (from the allowed vocabulary)
  - subject_focus      (what the frame centres on — a concrete element)
  - prev_link          (one sentence connecting back; null for shot 1)
  - next_link          (one sentence setting up next; null for last shot)

Also produce "sequence_arc" — one sentence describing the full video arc.

Target shots (in order):
{targets_block}

Return a SINGLE JSON object:
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

World brief:
---
{brief}
---

Abstraction level: {abstraction}/100. Apply as visual instruction: {abstraction_descriptor}

Storyboard for this specific shot:
  - target text:       "{target_text}"
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


def gemini_image(client, prompt: str, refs: list[bytes], max_attempts: int = 3) -> bytes | None:
    for attempt in range(1, max_attempts + 1):
        contents: list = []
        for prior in refs:
            contents.append(types.Part.from_bytes(data=prior, mime_type="image/png"))
        contents.append(prompt)
        try:
            resp = client.models.generate_content(model=IMG_MODEL, contents=contents, config=IMG_CONFIG)
        except Exception as e:
            print(f"  attempt {attempt}: exception {e}", file=sys.stderr)
            time.sleep(3)
            continue
        candidates = getattr(resp, "candidates", None) or []
        if not candidates:
            print(f"  attempt {attempt}: no candidates", file=sys.stderr)
            time.sleep(3)
            continue
        parts = getattr(candidates[0].content, "parts", None) if candidates[0].content else None
        if not parts:
            print(f"  attempt {attempt}: no parts (finish={getattr(candidates[0], 'finish_reason', None)})", file=sys.stderr)
            time.sleep(3)
            continue
        for part in parts:
            if getattr(part, "inline_data", None) is not None:
                return part.inline_data.data
        print(f"  attempt {attempt}: no inline_data", file=sys.stderr)
        time.sleep(3)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", required=True)
    ap.add_argument("--lyrics", required=True)
    ap.add_argument("--shots", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--filter", dest="filter_word", required=True)
    ap.add_argument("--abstraction", type=int, default=25)
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    keyframes_dir = run_dir / "keyframes"
    keyframes_dir.mkdir(exist_ok=True)

    shots_data = json.loads(Path(args.shots).read_text())
    shots = shots_data["shots"]
    lyrics_text = Path(args.lyrics).read_text()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    abstraction_desc = ABSTRACTION_DESCRIPTORS.get(args.abstraction, ABSTRACTION_DESCRIPTORS[25])

    # Pass A — world brief (cache)
    brief_path = run_dir / "character_brief.json"
    if brief_path.exists():
        brief = json.loads(brief_path.read_text())["brief"]
        print(f"[Pass A] cached: {brief[:120]}...")
    else:
        print("[Pass A] generating world brief...")
        pa_input = PASS_A_PROMPT.format(
            lyrics=lyrics_text,
            filter_word=args.filter_word,
            abstraction=args.abstraction,
            abstraction_descriptor=abstraction_desc,
        )
        t0 = time.time()
        resp = client.models.generate_content(model=LLM_MODEL, contents=pa_input)
        brief = resp.text.strip()
        brief_path.write_text(json.dumps({
            "brief": brief,
            "filter": args.filter_word,
            "abstraction": args.abstraction,
            "latency_s": round(time.time() - t0, 2),
        }, indent=2))
        print(f"[Pass A] {time.time() - t0:.1f}s — {brief[:120]}...")

    # Pass C — storyboard (cache)
    storyboard_path = run_dir / "storyboard.json"
    if storyboard_path.exists():
        storyboard = json.loads(storyboard_path.read_text())
        print(f"[Pass C] cached: {len(storyboard.get('shots', []))} shot beats")
    else:
        print(f"[Pass C] storyboarding {len(shots)} shots...")
        targets_block = "\n".join(
            f"  Shot {s['index']}: ({s['kind']}) {s['target_text']!r}"
            for s in shots
        )
        pc_input = PASS_C_PROMPT.format(
            brief=brief,
            n=len(shots),
            camera_intents=", ".join(CAMERA_INTENTS),
            targets_block=targets_block,
        )
        t0 = time.time()
        resp = client.models.generate_content(
            model=LLM_MODEL,
            contents=pc_input,
            config={"response_mime_type": "application/json"},
        )
        try:
            storyboard = json.loads(resp.text.strip())
        except json.JSONDecodeError as e:
            (run_dir / "storyboard_raw.txt").write_text(resp.text)
            sys.exit(f"[Pass C] JSON decode failed: {e}")
        storyboard_path.write_text(json.dumps(storyboard, indent=2))
        print(f"[Pass C] {time.time() - t0:.1f}s — {len(storyboard.get('shots', []))} beats")

    # Pass B + keyframe per shot
    sb_shots = {s["index"]: s for s in storyboard.get("shots", [])}
    image_prompts_path = run_dir / "image_prompts.json"
    image_prompts = json.loads(image_prompts_path.read_text()) if image_prompts_path.exists() else {}

    # Rolling identity reference window — load last N existing keyframes
    recent_refs: list[bytes] = []
    for s in shots:
        idx = s["index"]
        kf_path = keyframes_dir / f"keyframe_{idx:03d}.png"
        if kf_path.exists():
            recent_refs.append(kf_path.read_bytes())
            recent_refs = recent_refs[-IDENTITY_REF_WINDOW:]
            continue
        sb = sb_shots.get(idx)
        if not sb:
            print(f"[shot {idx}] no storyboard entry — skipping", file=sys.stderr)
            continue
        ip_key = f"shot_{idx:03d}"
        if ip_key in image_prompts:
            image_prompt = image_prompts[ip_key]
        else:
            pb_input = PASS_B_PROMPT.format(
                brief=brief,
                abstraction=args.abstraction,
                abstraction_descriptor=abstraction_desc,
                target_text=s["target_text"],
                beat=sb.get("beat", ""),
                subject_focus=sb.get("subject_focus", ""),
                camera_intent=sb.get("camera_intent", "static hold"),
                prev_link=sb.get("prev_link") or "null",
                next_link=sb.get("next_link") or "null",
            )
            t0 = time.time()
            resp = client.models.generate_content(model=LLM_MODEL, contents=pb_input)
            image_prompt = resp.text.strip().strip('"').strip()
            image_prompts[ip_key] = image_prompt
            image_prompts_path.write_text(json.dumps(image_prompts, indent=2))
            print(f"[shot {idx:3d}] Pass B {time.time() - t0:.1f}s: {image_prompt[:80]}...")

        t0 = time.time()
        # Aspect ratio is enforced by IMG_CONFIG (imageConfig.aspectRatio=16:9).
        img_bytes = gemini_image(client, image_prompt, recent_refs)
        if img_bytes is None:
            print(f"[shot {idx:3d}] ERROR no image; leaving gap, continuing", file=sys.stderr)
            continue
        kf_path.write_bytes(img_bytes)
        recent_refs.append(img_bytes)
        recent_refs = recent_refs[-IDENTITY_REF_WINDOW:]
        print(f"[shot {idx:3d}] keyframe {time.time() - t0:.1f}s -> {kf_path.name}")

    print(f"\n[done] keyframes in {keyframes_dir}")


if __name__ == "__main__":
    main()
