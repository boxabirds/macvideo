#!/usr/bin/env python
"""POC 18 — LLM filter chooser (Pass 0). Gemini reads lyrics + accepted palette
and picks the best filter per song, with rationale + runners-up."""

import json
import os
import sys
import time
from html import escape
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent.parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))
from pocs._lib.poc_helpers import make_run_dir, save_prompts

ENV_FILE = REPO_ROOT / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

if "GEMINI_API_KEY" not in os.environ:
    print("ERROR: GEMINI_API_KEY not set.", file=sys.stderr)
    sys.exit(1)

from google import genai

LLM_MODEL = "gemini-3-flash-preview"
STYLES_YAML = REPO_ROOT / "config" / "styles.yaml"
MUSIC_DIR = REPO_ROOT / "music"

CHOOSER_PROMPT = """You are a music video director. You have one song's full lyrics and a palette of available visual styles. Pick the ONE style that best fits this song's mood, imagery, and central metaphor. Then rank 3-5 runners-up.

Song lyrics:
---
{lyrics}
---

Available styles (choose exactly one):
{styles_block}

Your choice must be driven by specifics of the song — name features of the lyrics (imagery, metaphor, mood, pacing) that the style matches. Do not use vague descriptors like "evocative" or "atmospheric" on their own.

Return ONLY a JSON object with this structure:
{{
  "chosen_filter": "<exact filter name from the list>",
  "rationale": "2-3 sentences — cite specific lyrical moments and why the chosen style serves them",
  "runners_up": [
    {{"filter": "<name>", "why": "one-line reason"}},
    {{"filter": "<name>", "why": "one-line reason"}},
    {{"filter": "<name>", "why": "one-line reason"}}
  ]
}}"""


def clean_lyrics(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        lines.append(s)
    return "\n".join(lines).strip()


def main():
    styles = yaml.safe_load(STYLES_YAML.read_text())
    accepted = [f for f in styles["filters"] if f["status"] == "accepted"]
    allowed_names = {f["name"] for f in accepted}
    styles_block = "\n".join(
        f"  - {f['name']} ({f['category']}): {f.get('description','')}"
        for f in accepted
    )

    song_paths = sorted(MUSIC_DIR.glob("*.txt"))
    if not song_paths:
        print("No lyric .txt files in music/.", file=sys.stderr)
        sys.exit(1)

    run_dir = make_run_dir(__file__)
    print(f"Run dir: {run_dir}")
    print(f"Accepted filters: {len(accepted)}")

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    all_results = {}
    for song_path in song_paths:
        song_stem = song_path.stem
        lyrics = clean_lyrics(song_path.read_text())

        prompt = CHOOSER_PROMPT.format(lyrics=lyrics, styles_block=styles_block)
        print(f"\n=== {song_stem} ===")
        t0 = time.time()
        resp = client.models.generate_content(
            model=LLM_MODEL,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        dt = time.time() - t0
        raw = resp.text.strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"  ERROR: invalid JSON: {e}", file=sys.stderr)
            print(raw, file=sys.stderr)
            continue

        chosen = parsed.get("chosen_filter")
        if chosen not in allowed_names:
            print(f"  WARNING: chosen filter {chosen!r} not in accepted list", file=sys.stderr)

        parsed["latency_s"] = round(dt, 2)
        parsed["usage"] = (
            resp.usage_metadata.model_dump() if getattr(resp, "usage_metadata", None) else None
        )
        (run_dir / f"{song_stem}.json").write_text(json.dumps(parsed, indent=2, default=str))
        all_results[song_stem] = parsed

        print(f"  chosen: {chosen}  ({dt:.2f}s)")
        print(f"  rationale: {parsed.get('rationale', '')[:200]}")
        for i, ru in enumerate(parsed.get("runners_up", []), 1):
            print(f"    {i}. {ru.get('filter')} — {ru.get('why')}")

    # HTML report
    rows = []
    for song_stem, res in all_results.items():
        chosen = res.get("chosen_filter", "?")
        slug = chosen.replace(" ", "_")
        gallery_img = f"../../17-filter-gallery/outputs/latest/{song_stem}/{slug}/keyframe.png"
        gallery_clip = f"../../17-filter-gallery/outputs/latest/{song_stem}/{slug}/clip.mp4"
        runners_html = "".join(
            f"<li><b>{escape(r.get('filter',''))}</b> — {escape(r.get('why',''))}</li>"
            for r in res.get("runners_up", [])
        )
        rows.append(f"""
<section>
  <h2>{escape(song_stem)}</h2>
  <div class="choice">
    <div class="pick">
      <h3>{escape(chosen)}</h3>
      <p>{escape(res.get('rationale',''))}</p>
      <a href="{gallery_img}"><img src="{gallery_img}" loading="lazy"></a>
      <p><a href="{gallery_clip}">▶ play gallery clip</a></p>
    </div>
    <div class="runners">
      <h4>Runners-up</h4>
      <ol>{runners_html}</ol>
    </div>
  </div>
</section>""")

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>POC 18 — Filter Chooser</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, sans-serif; margin: 1.5rem; max-width: 1400px; }}
  section {{ margin-bottom: 2rem; border-top: 1px solid #0003; padding-top: 1rem; }}
  .choice {{ display: flex; gap: 2rem; align-items: flex-start; }}
  .pick {{ flex: 1; max-width: 560px; }}
  .pick img {{ width: 100%; max-width: 560px; border: 1px solid #0003; }}
  .runners {{ flex: 1; }}
  h3 {{ margin: 0; font-size: 1.4rem; }}
  h4 {{ margin: 0 0 .5rem; }}
  ol {{ padding-left: 1.2rem; }}
</style>
</head>
<body>
<h1>POC 18 — LLM Filter Chooser</h1>
<p>Pass 0 picks one filter per song from the accepted palette. Thumbnails link to POC 17's already-rendered keyframe for the chosen filter.</p>
{''.join(rows)}
</body>
</html>
"""
    (run_dir / "report.html").write_text(html)

    save_prompts(run_dir, {
        "llm_model": LLM_MODEL,
        "chooser_prompt_template": CHOOSER_PROMPT,
        "accepted_filters": [f["name"] for f in accepted],
        "per_song_results": all_results,
    })
    print(f"\nReport: {run_dir / 'report.html'}")


if __name__ == "__main__":
    main()
