#!/usr/bin/env python
"""POC 19 — abstraction spectrum per chosen filter per song.

Depends on POC 18's output. For every song, uses POC 18's chosen filter and
renders 5 abstraction levels (0, 25, 50, 75, 100). Live progress + final gallery."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional

import yaml

HERE = Path(__file__).resolve().parent.parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))
from pocs._lib.poc_helpers import make_run_dir, save_prompts  # noqa: E402

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
IMG_MODEL = "gemini-3.1-flash-image-preview"
MUSIC_DIR = REPO_ROOT / "music"
CACHE_DIR = REPO_ROOT / "pocs" / "17-filter-gallery" / "cache"
POC18_OUTPUTS = REPO_ROOT / "pocs" / "18-filter-chooser" / "outputs"

WIDTH = 512
HEIGHT = 320
FPS = 10
NUM_FRAMES = 17

MOTION_PROMPT = "gentle slow camera settle, subtle ambient motion within the frame, no abrupt movement"
TECH_NEGATIVE = "blurry, low quality, worst quality, distorted, watermark, subtitle"

ABSTRACTION_LEVELS = [0, 25, 50, 75, 100]

ABSTRACTION_DESCRIPTORS = {
    0: "fully representational, photographic clarity, subjects rendered as concrete recognisable form with grounded proportions and depth",
    25: "loosely expressive — brushwork and line quality given primacy over accuracy; subjects still clearly legible but simplified; distortion and gesture honoured",
    50: "heavily stylised — figures become simplified masses and volumes, architecture reduced to structural shapes; recognisable but abstracted",
    75: "predominantly abstract — the figure becomes a dark mass or smear, the setting becomes rectangles of light and shadow, details replaced by rhythm and weight",
    100: "pure abstraction — no recognisable figures, objects, or settings; composition is colour field, line, rhythm, texture",
}

MLX_VIDEO_CMD = [
    "uv", "run", "mlx_video.ltx_2.generate",
    "--seed", "42",
    "--pipeline", "dev-two-stage",
    "--model-repo", "prince-canuma/LTX-2.3-dev",
    "--text-encoder-repo", "mlx-community/gemma-3-12b-it-bf16",
    "--width", str(WIDTH),
    "--height", str(HEIGHT),
    "--num-frames", str(NUM_FRAMES),
    "--fps", str(FPS),
    "--image-strength", "1.0",
    "--image-frame-idx", "0",
    "--negative-prompt", TECH_NEGATIVE,
]

PASS_A_PROMPT = """You are a music video director for a song that will be rendered ENTIRELY in the "{filter_word}" style.

Song lyrics:
---
{lyrics}
---

Write a character/world brief (5-8 sentences). Every shot exists WITHIN the {filter_word} style. Describe the narrator, the central metaphor, the setting, and how the style manifests (materials, textures, palette, line quality, lighting). Concrete visual cues only. Describe what IS present.

Return ONLY the brief as a single paragraph."""

PASS_B_PROMPT = """You are a music video director generating ONE image prompt for a keyframe.

Song lyrics:
---
{lyrics}
---

Persistent world brief:
---
{brief}
---

Target line (first line of the song): "{target_line}"

Abstraction level: {abstraction}/100.
Apply this abstraction: {abstraction_descriptor}

Write ONE image prompt (3-4 sentences). Depict the beat of the line in context, at the specified abstraction level. Honour the world brief. Describe what IS present. No emotional labels.

Return ONLY the final image prompt as a single paragraph."""


SECTION_MARKER_RE = re.compile(r"^\*+\[[^\]]*\]\*+\s*$")


def clean_lyrics(raw: str) -> str:
    return "\n".join(
        s for s in (ln.strip() for ln in raw.splitlines())
        if s and not s.startswith("#")
    )


def first_line_from_aligned(aligned: dict) -> dict:
    lines = aligned.get("lines", [])
    words = aligned.get("words", [])
    if not lines or not words:
        raise RuntimeError("aligned.json missing lines/words")
    first_text = lines[0]["text"]
    tokens = re.findall(r"[\w']+", first_text)
    n = min(len(tokens), len(words))
    return {
        "text": first_text.strip(),
        "start": float(words[0]["start"]),
        "end": float(words[n - 1]["end"]),
    }


def load_chosen_filters() -> dict[str, str]:
    """Read the latest POC 18 run and return {song_stem: chosen_filter}."""
    latest = POC18_OUTPUTS / "latest"
    if not latest.exists():
        raise RuntimeError(f"POC 18 output missing at {latest}. Run POC 18 first.")
    out: dict[str, str] = {}
    for f in latest.iterdir():
        if f.suffix == ".json" and f.stem not in ("prompts", "run_state"):
            data = json.loads(f.read_text())
            chosen = data.get("chosen_filter")
            if chosen:
                out[f.stem] = chosen
    return out


def gemini_image_with_retry(client, contents, max_attempts: int = 3):
    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.models.generate_content(model=IMG_MODEL, contents=contents)
        except Exception as e:
            print(f"  image attempt {attempt}: exception {e}", file=sys.stderr)
            time.sleep(2)
            continue
        candidates = getattr(resp, "candidates", None) or []
        if not candidates:
            time.sleep(2); continue
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) if content else None
        if not parts:
            finish = getattr(candidates[0], "finish_reason", None)
            print(f"  image attempt {attempt}: empty parts (finish={finish})", file=sys.stderr)
            time.sleep(2); continue
        for p in parts:
            if getattr(p, "inline_data", None) is not None:
                return p.inline_data.data
        time.sleep(2)
    return None


def fmt_duration(seconds: float) -> str:
    if seconds < 60: return f"{int(seconds)} s"
    m = seconds / 60
    if m < 60: return f"{m:.1f} min"
    return f"{m/60:.2f} h"


def write_progress(run_dir: Path, tasks: list, results: dict, start_time: float,
                   current: Optional[tuple], done: bool, songs: list, chosen_filters: dict):
    total = len(tasks)
    completed = sum(1 for v in results.values() if v.get("status") == "done")
    failed = sum(1 for v in results.values() if v.get("status") == "failed")
    pending = total - completed - failed
    elapsed = time.time() - start_time
    eta = fmt_duration((elapsed / completed) * pending) if completed else "—"
    refresh = "" if done else '<meta http-equiv="refresh" content="15">'

    # Rows = abstraction levels, cols = songs
    header = ["<th></th>"] + [
        f"<th>{escape(s)}<div class='sub'>filter: {escape(chosen_filters[s])}</div></th>"
        for s in songs
    ]
    rows_html = []
    for N in ABSTRACTION_LEVELS:
        cells = [f"<th scope='row'>N = {N}</th>"]
        for song in songs:
            key = f"{song}::{N}"
            r = results.get(key, {})
            status = r.get("status", "pending")
            if current and current == (song, N):
                status = "running"
            thumb = ""
            if status == "done":
                thumb = f"<img src='{song}/abstraction_{N:03d}/keyframe.png' loading='lazy'>"
            err = r.get("error", "")
            err_html = f"<div class='err'>{escape(err)[:80]}</div>" if err else ""
            cells.append(f"<td class='{status}'>{thumb}<div class='meta'>{status}</div>{err_html}</td>")
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    pct = (completed + failed) / total * 100 if total else 0
    current_html = (
        f"<div class='current'>Currently: <b>{escape(current[0])}</b> × N={current[1]}</div>"
        if current and not done else ""
    )

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>POC 19 — Abstraction Gallery Progress</title>{refresh}
<style>
  :root{{color-scheme:light dark}}body{{font-family:-apple-system,sans-serif;margin:1.5rem}}
  .summary{{display:flex;gap:2rem;margin:1rem 0;flex-wrap:wrap}}.summary .num{{font-size:1.6rem;font-weight:600}}
  .bar{{height:10px;background:#0003;border-radius:4px;overflow:hidden}}.bar .fill{{height:100%;background:#4c9;transition:width .5s}}
  .current{{margin:1rem 0;padding:.75rem 1rem;background:#fe8;color:#000;border-radius:6px}}
  table{{border-collapse:collapse;width:100%;font-size:12px}}
  th,td{{border:1px solid #0003;padding:.3rem;vertical-align:top;text-align:left}}
  th{{background:#0001;position:sticky;top:0}}th[scope=row]{{white-space:nowrap;font-weight:500}}
  .sub{{font-size:10px;opacity:.6;font-weight:400}}
  td{{width:240px;height:180px}}td img{{width:100%;height:140px;object-fit:cover;display:block}}
  td .meta{{font-size:10px;margin-top:2px}}
  td.pending{{background:#0001}}td.running{{background:#fe8}}td.done{{background:#dfd}}td.failed{{background:#fdd}}
  td .err{{color:#a00;font-size:10px}}
</style></head><body>
<h1>POC 19 — Abstraction Gallery</h1>
<div class="sub">run: {escape(run_dir.name)}</div>
<div class="summary">
  <div><div>Completed</div><div class="num">{completed}/{total}</div></div>
  <div><div>Failed</div><div class="num">{failed}</div></div>
  <div><div>Elapsed</div><div class="num">{fmt_duration(elapsed)}</div></div>
  <div><div>ETA</div><div class="num">{eta}</div></div>
  <div style="flex:1;min-width:250px"><div>Progress ({pct:.0f}%)</div><div class="bar"><div class="fill" style="width:{pct}%"></div></div></div>
</div>
{current_html}
<table><thead><tr>{''.join(header)}</tr></thead><tbody>{''.join(rows_html)}</tbody></table>
<p class="sub">Last updated: {escape(datetime.now().isoformat(timespec='seconds'))}. {'All done.' if done else 'Auto-refreshes every 15 s.'}</p>
</body></html>
"""
    (run_dir / "progress.html").write_text(html)


def write_gallery(run_dir: Path, songs: list, chosen_filters: dict, results: dict):
    header = ["<th></th>"] + [
        f"<th>{escape(s)}<div class='sub'>filter: {escape(chosen_filters[s])}</div></th>"
        for s in songs
    ]
    rows_html = []
    for N in ABSTRACTION_LEVELS:
        cells = [f"<th scope='row'>N = {N}</th>"]
        for song in songs:
            key = f"{song}::{N}"
            r = results.get(key, {})
            if r.get("status") == "done":
                base = f"{song}/abstraction_{N:03d}"
                cells.append(
                    f"<td class='done'>"
                    f"<video src='{base}/clip.mp4' poster='{base}/keyframe.png' "
                    f"controls preload='none' muted loop></video>"
                    f"<div class='meta'><a href='{base}/prompts.json'>prompts</a></div>"
                    f"</td>"
                )
            else:
                err = escape(r.get("error", ""))[:120]
                cells.append(f"<td class='failed'><div class='meta'>{r.get('status','pending')}</div><div class='err'>{err}</div></td>")
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>POC 19 — Abstraction Gallery</title>
<style>
  :root{{color-scheme:light dark}}body{{font-family:-apple-system,sans-serif;margin:1.5rem}}
  table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #0003;padding:.3rem;vertical-align:top;text-align:left}}
  th{{background:#0001}}th[scope=row]{{white-space:nowrap}}
  .sub{{font-size:10px;opacity:.6;font-weight:400}}
  td{{width:360px;height:250px}}td img{{width:100%;height:200px;object-fit:cover;display:block}}
  td video{{width:100%;height:200px;object-fit:cover;display:block;background:#000}}
  td .meta{{font-size:11px;margin-top:4px}}td.done{{background:#efe}}td.failed{{background:#fdd}}
  td .err{{color:#a00;font-size:10px}}a{{text-decoration:none}}
</style></head><body>
<h1>POC 19 — Abstraction Gallery</h1>
<p>5 abstraction levels × 3 songs, each in its POC-18-chosen filter. Click any thumbnail to play.</p>
<table><thead><tr>{''.join(header)}</tr></thead><tbody>{''.join(rows_html)}</tbody></table>
</body></html>
"""
    (run_dir / "gallery.html").write_text(html)


def main():
    chosen_filters = load_chosen_filters()
    song_paths = sorted(
        MUSIC_DIR.glob("*.wav"),
        key=lambda p: list(chosen_filters.keys()).index(p.stem) if p.stem in chosen_filters else 999
    )
    song_paths = [p for p in song_paths if p.stem in chosen_filters]
    if not song_paths:
        print("No songs match POC 18's chosen filters.", file=sys.stderr)
        sys.exit(1)

    run_dir = make_run_dir(__file__)
    print(f"Run dir: {run_dir}")
    print(f"Chosen filters per song: {chosen_filters}")

    (run_dir / "chosen_filters.json").write_text(json.dumps(chosen_filters, indent=2))

    # Resolve first lines
    songs_info: list[dict] = []
    for sp in song_paths:
        aligned_path = CACHE_DIR / sp.stem / "aligned.json"
        if not aligned_path.exists():
            # Fall back to POC 7's single-song output for my-little-blackbird
            alt = REPO_ROOT / "pocs" / "07-whisperx" / "outputs" / "aligned.json"
            if sp.stem == "my-little-blackbird" and alt.exists():
                aligned_path = alt
            else:
                print(f"ERROR: aligned.json missing for {sp.stem}. Run POC 17 first "
                      f"(it caches aligned.json for all songs).", file=sys.stderr)
                sys.exit(2)
        aligned = json.loads(aligned_path.read_text())
        first = first_line_from_aligned(aligned)
        lyrics = clean_lyrics((MUSIC_DIR / f"{sp.stem}.txt").read_text())
        songs_info.append({
            "stem": sp.stem,
            "filter": chosen_filters[sp.stem],
            "lyrics": lyrics,
            "first_line": first,
        })
        print(f"  {sp.stem}: filter={chosen_filters[sp.stem]}, first={first['text']!r}")

    song_stems = [s["stem"] for s in songs_info]

    # Task list
    tasks = [(s["stem"], N) for s in songs_info for N in ABSTRACTION_LEVELS]
    results: dict[str, dict] = {}

    start = time.time()
    write_progress(run_dir, tasks, results, start, None, False, song_stems, chosen_filters)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # Pass A per song (cached, reused across all abstraction levels for that song)
    briefs: dict[str, str] = {}
    for s in songs_info:
        print(f"\n[Pass A] {s['stem']} ({s['filter']})")
        pass_a = PASS_A_PROMPT.format(lyrics=s["lyrics"], filter_word=s["filter"])
        t0 = time.time()
        resp = client.models.generate_content(model=LLM_MODEL, contents=pass_a)
        briefs[s["stem"]] = resp.text.strip()
        print(f"  {time.time()-t0:.2f}s")

    # Main loop: song × abstraction
    for i, (song_stem, N) in enumerate(tasks):
        key = f"{song_stem}::{N}"
        s = next(x for x in songs_info if x["stem"] == song_stem)
        out_dir = run_dir / song_stem / f"abstraction_{N:03d}"
        clip_path = out_dir / "clip.mp4"
        if clip_path.exists():
            results[key] = {"status": "done", "cached": True}
            write_progress(run_dir, tasks, results, start, None, False, song_stems, chosen_filters)
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        write_progress(run_dir, tasks, results, start, (song_stem, N), False, song_stems, chosen_filters)
        print(f"\n[{i+1}/{len(tasks)}] {song_stem} × N={N}")

        try:
            pass_b = PASS_B_PROMPT.format(
                lyrics=s["lyrics"], brief=briefs[song_stem],
                target_line=s["first_line"]["text"],
                abstraction=N,
                abstraction_descriptor=ABSTRACTION_DESCRIPTORS[N],
            )
            t0 = time.time()
            pb_resp = client.models.generate_content(model=LLM_MODEL, contents=pass_b)
            image_prompt = pb_resp.text.strip().strip('"').strip()
            pass_b_s = time.time() - t0

            t0 = time.time()
            image_bytes = gemini_image_with_retry(client, [image_prompt])
            img_s = time.time() - t0
            if image_bytes is None:
                raise RuntimeError("Gemini image failed after retries")
            keyframe_path = out_dir / "keyframe.png"
            keyframe_path.write_bytes(image_bytes)

            ltx_prompt = f"{MOTION_PROMPT}. {image_prompt}"
            t0 = time.time()
            cmd = list(MLX_VIDEO_CMD) + [
                "--prompt", ltx_prompt,
                "--image", str(keyframe_path),
                "--output-path", str(clip_path),
            ]
            log_path = out_dir / "ltx.log"
            with log_path.open("w") as logf:
                logf.write(f"CMD: {' '.join(cmd)}\n\n")
                res = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT)
            ltx_s = time.time() - t0
            if res.returncode != 0 or not clip_path.exists():
                raise RuntimeError(f"LTX failed (rc={res.returncode})")

            save_prompts(out_dir, {
                "song": song_stem,
                "filter": s["filter"],
                "abstraction": N,
                "abstraction_descriptor": ABSTRACTION_DESCRIPTORS[N],
                "first_line": s["first_line"],
                "pass_a_brief": briefs[song_stem],
                "pass_b_input": pass_b,
                "image_prompt": image_prompt,
                "ltx_final_prompt": ltx_prompt,
                "timings_s": {"pass_b": pass_b_s, "image": img_s, "ltx": ltx_s},
            })
            results[key] = {"status": "done"}
            print(f"    ✓ done in {pass_b_s+img_s+ltx_s:.1f}s")
        except Exception as e:
            (out_dir / "error.txt").write_text(f"{e}\n\n{traceback.format_exc()}")
            results[key] = {"status": "failed", "error": str(e)}
            print(f"    ✗ failed: {e}", file=sys.stderr)

        (run_dir / "run_state.json").write_text(json.dumps({
            "tasks": tasks, "results": results, "start_time": start,
        }, indent=2, default=str))
        write_progress(run_dir, tasks, results, start, None, False, song_stems, chosen_filters)

    write_gallery(run_dir, song_stems, chosen_filters, results)
    write_progress(run_dir, tasks, results, start, None, True, song_stems, chosen_filters)

    elapsed = time.time() - start
    done = sum(1 for v in results.values() if v.get("status") == "done")
    failed = sum(1 for v in results.values() if v.get("status") == "failed")
    print(f"\n===\nDone: {done}/{len(tasks)}, failed: {failed}, elapsed {fmt_duration(elapsed)}")
    print(f"Gallery: {run_dir / 'gallery.html'}")


if __name__ == "__main__":
    main()
