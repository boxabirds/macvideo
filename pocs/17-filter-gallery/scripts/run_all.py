#!/usr/bin/env python
"""POC 17 orchestrator — every song × every filter, with live progress HTML."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Optional

import yaml

HERE = Path(__file__).resolve().parent.parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))
from pocs._lib.poc_helpers import make_run_dir, save_prompts  # noqa: E402

# --- config ------------------------------------------------------------------

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
from google.genai import types

STYLES_YAML = REPO_ROOT / "config" / "styles.yaml"
MUSIC_DIR = REPO_ROOT / "music"
CACHE_DIR = HERE / "cache"
CACHE_DIR.mkdir(exist_ok=True)

LLM_MODEL = "gemini-3-flash-preview"
IMG_MODEL = "gemini-3.1-flash-image-preview"

WIDTH = 512
HEIGHT = 320
FPS = 10
NUM_FRAMES = 17  # 1 + 8*2 = 1.7 s at 10 fps, minimal compute but enough motion

MOTION_PROMPT = (
    "gentle slow camera settle, subtle ambient motion within the frame, "
    "no abrupt movement"
)
TECH_NEGATIVE = "blurry, low quality, worst quality, distorted, watermark, subtitle"

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


# --- prompts -----------------------------------------------------------------

PASS_A_PROMPT = """You are a music video director for a song that will be rendered ENTIRELY in the "{filter_word}" style.

Song lyrics:
---
{lyrics}
---

Write a character/world brief (5-8 sentences) such that every shot of this
song exists WITHIN the {filter_word} style — not as a photorealistic scene
decorated with {filter_word} details, but as a scene that IS {filter_word}:
characters are made of {filter_word} materials, settings follow {filter_word}
rules, lighting behaves as {filter_word} lighting does.

Describe:
  - the narrator (appearance, age, clothing, demeanour; how {filter_word} manifests on them)
  - the central metaphorical subject (here the blackbird if present, else whatever the song orbits)
  - the primary setting (interior / exterior / atmosphere, all in {filter_word})
  - materials, textures, palette, line quality, lighting behaviour — all in {filter_word}

Concrete visual language only. Describe what IS present; never what is absent.

Return ONLY the brief as a single paragraph."""

PASS_B_PROMPT = """You are a music video director generating ONE image prompt for a keyframe.

Song lyrics:
---
{lyrics}
---

Persistent character & world brief (the whole song lives in this):
---
{brief}
---

Target line (the first sung moment of the song): "{target_line}"

Write ONE image-generation prompt (3-4 sentences) for the keyframe representing
this line in the context of the full song. The image must:
  - depict the beat/mood the line opens the song with (not just a literal reading)
  - honour the world brief (same character, same setting, same style)
  - describe only what IS present in the frame
  - use concrete visual cues only

Return ONLY the final image prompt as a single paragraph."""


# --- helpers -----------------------------------------------------------------

SECTION_MARKER_RE = re.compile(r"^\*+\[[^\]]*\]\*+\s*$")


def clean_lyrics(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        lines.append(s)
    return "\n".join(lines).strip()


def ensure_aligned(song_path: Path) -> Path:
    """Demucs-separate vocals then force-align ground-truth lyrics. Cached per song."""
    song_cache = CACHE_DIR / song_path.stem
    aligned_path = song_cache / "aligned.json"
    vocals_path = song_cache / "vocals.wav"
    lyrics_path = MUSIC_DIR / f"{song_path.stem}.txt"

    if not lyrics_path.exists():
        raise RuntimeError(f"Missing lyrics: {lyrics_path}")

    if aligned_path.exists():
        return aligned_path

    song_cache.mkdir(parents=True, exist_ok=True)

    # Demucs into a scratch dir, then copy vocals out
    stems_parent = song_cache / "stems"
    demucs_vocals = stems_parent / "htdemucs_6s" / song_path.stem / "vocals.wav"
    if not demucs_vocals.exists():
        print(f"[transcribe] Demucs on {song_path.name} ...", flush=True)
        subprocess.run(
            ["uv", "run", "demucs", "-n", "htdemucs_6s",
             str(song_path), "-o", str(stems_parent)],
            check=True,
        )
    if not vocals_path.exists():
        vocals_path.write_bytes(demucs_vocals.read_bytes())

    # Forced alignment
    print(f"[transcribe] forced-align {song_path.name} ...", flush=True)
    force_align_script = REPO_ROOT / "pocs" / "07-whisperx" / "scripts" / "force_align.py"
    subprocess.run(
        ["uv", "run", "python", str(force_align_script),
         str(vocals_path), str(lyrics_path), str(aligned_path)],
        check=True,
    )
    return aligned_path


def first_line_from_aligned(aligned: dict) -> dict:
    """Return the first lyric line's {text, start, end}.

    force_align.py writes a `lines` list (line_idx + text) and a parallel `words`
    list in the same order as the ground-truth lyrics. The first N words of
    `words` correspond to the first line's tokens.
    """
    lines = aligned.get("lines", [])
    words = aligned.get("words", [])
    if not lines or not words:
        raise RuntimeError("aligned.json missing lines or words")
    first_text = lines[0]["text"]
    tokens = re.findall(r"[\w']+", first_text)
    if not tokens:
        raise RuntimeError(f"First line has no tokens: {first_text!r}")
    n = min(len(tokens), len(words))
    line_words = words[:n]
    return {
        "text": first_text.strip(),
        "start": float(line_words[0]["start"]),
        "end": float(line_words[-1]["end"]),
    }


def gemini_image_with_retry(client, contents, max_attempts: int = 3) -> Optional[bytes]:
    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.models.generate_content(model=IMG_MODEL, contents=contents)
        except Exception as e:
            print(f"  image attempt {attempt}/{max_attempts} exception: {e}", file=sys.stderr)
            time.sleep(2)
            continue
        candidates = getattr(resp, "candidates", None) or []
        if not candidates:
            print(f"  image attempt {attempt}: no candidates", file=sys.stderr)
            time.sleep(2)
            continue
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) if content else None
        if not parts:
            finish = getattr(candidates[0], "finish_reason", None)
            print(f"  image attempt {attempt}: empty parts (finish={finish})", file=sys.stderr)
            time.sleep(2)
            continue
        for p in parts:
            if getattr(p, "inline_data", None) is not None:
                return p.inline_data.data
        time.sleep(2)
    return None


# --- progress HTML ------------------------------------------------------------

def fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)} s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f} min"
    hours = minutes / 60
    return f"{hours:.2f} h"


def write_progress(run_dir: Path, tasks: list, results: dict, start_time: float,
                   current: Optional[tuple], done_flag: bool, songs: list,
                   filters: list) -> None:
    total = len(tasks)
    completed = sum(1 for _, v in results.items() if v.get("status") == "done")
    failed = sum(1 for _, v in results.items() if v.get("status") == "failed")
    pending = total - completed - failed

    elapsed = time.time() - start_time
    if completed > 0:
        avg = elapsed / completed
        eta_s = avg * pending
        eta_str = fmt_duration(eta_s)
    else:
        eta_str = "—"

    refresh_meta = "" if done_flag else '<meta http-equiv="refresh" content="15">'

    # Build grid: rows = filters, cols = songs
    col_song_keys = [s["stem"] for s in songs]
    rows_html = []
    for filt in filters:
        cells = [f"<th scope='row'>{escape(filt['name'])}<div class='status'>{escape(filt['status'])}</div></th>"]
        for song_stem in col_song_keys:
            key = f"{song_stem}::{filt['name']}"
            r = results.get(key, {})
            status = r.get("status", "pending")
            if current and current == (song_stem, filt["name"]):
                status = "running"
            thumb = ""
            video = ""
            if status == "done":
                rel = f"{song_stem}/{filt['name'].replace(' ', '_')}"
                thumb = f"<img src='{rel}/keyframe.png' loading='lazy' />"
                video = f"<a href='{rel}/clip.mp4'>▶</a>"
            err = ""
            if status == "failed":
                err = f"<div class='err'>{escape(r.get('error', ''))[:80]}</div>"
            cells.append(
                f"<td class='{status}'>"
                f"{thumb}"
                f"<div class='meta'>{status}{video}</div>"
                f"{err}"
                f"</td>"
            )
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    # Header row: one empty corner + one column per song
    header_cells = ["<th></th>"]
    for s in songs:
        first = s["first_line"]["text"]
        header_cells.append(
            f"<th scope='col'>{escape(s['stem'])}<div class='sub'>{escape(first[:40])}</div></th>"
        )

    pct = (completed + failed) / total * 100 if total else 0
    current_html = ""
    if current and not done_flag:
        current_html = f"<div class='current'>Currently generating: <b>{escape(current[0])}</b> × <b>{escape(current[1])}</b></div>"

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>POC 17 — Filter Gallery Progress</title>
{refresh_meta}
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, sans-serif; margin: 1.5rem; }}
  h1 {{ margin: 0 0 .5rem; }}
  .summary {{ display: flex; gap: 2rem; margin: 1rem 0; flex-wrap: wrap; }}
  .summary .num {{ font-size: 1.6rem; font-weight: 600; }}
  .bar {{ height: 10px; background: #0003; border-radius: 4px; overflow: hidden; }}
  .bar .fill {{ height: 100%; background: #4c9; transition: width .5s; }}
  .current {{ margin: 1rem 0; padding: .75rem 1rem; background: #fe8; color: #000; border-radius: 6px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
  th, td {{ border: 1px solid #0003; padding: .3rem; vertical-align: top; text-align: left; }}
  th {{ background: #0001; position: sticky; top: 0; z-index: 1; }}
  th[scope=row] {{ white-space: nowrap; font-weight: 500; }}
  .status {{ font-size: 10px; opacity: .6; }}
  .sub {{ font-size: 10px; opacity: .6; font-weight: 400; }}
  td {{ width: 180px; height: 130px; }}
  td img {{ width: 100%; height: 90px; object-fit: cover; display: block; }}
  td .meta {{ font-size: 10px; margin-top: 2px; }}
  td.pending {{ background: #0001; }}
  td.running {{ background: #fe8; }}
  td.done    {{ background: #dfd; }}
  td.failed  {{ background: #fdd; }}
  td .err {{ color: #a00; font-size: 10px; }}
  a {{ text-decoration: none; padding: 0 4px; }}
</style>
</head>
<body>
<h1>POC 17 — Filter Gallery</h1>
<div class="sub">run: {escape(run_dir.name)}</div>
<div class="summary">
  <div><div>Completed</div><div class="num">{completed}/{total}</div></div>
  <div><div>Failed</div><div class="num">{failed}</div></div>
  <div><div>Elapsed</div><div class="num">{fmt_duration(elapsed)}</div></div>
  <div><div>ETA</div><div class="num">{eta_str}</div></div>
  <div style="flex:1; min-width: 250px;"><div>Progress ({pct:.0f}%)</div><div class="bar"><div class="fill" style="width:{pct}%"></div></div></div>
</div>
{current_html}
<table>
<thead><tr>{''.join(header_cells)}</tr></thead>
<tbody>
{''.join(rows_html)}
</tbody>
</table>
<p class="sub">Last updated: {escape(datetime.now().isoformat(timespec='seconds'))}. {'All done.' if done_flag else 'Auto-refreshes every 15 s.'}</p>
</body>
</html>
"""
    (run_dir / "progress.html").write_text(html)


def write_gallery(run_dir: Path, songs: list, filters: list, results: dict) -> None:
    """Final static gallery — same grid, no refresh, no 'running' state."""
    col_song_keys = [s["stem"] for s in songs]
    rows_html = []
    for filt in filters:
        cells = [f"<th scope='row'>{escape(filt['name'])}<div class='status'>{escape(filt['status'])}</div><div class='cat'>{escape(filt.get('category',''))}</div></th>"]
        for song_stem in col_song_keys:
            key = f"{song_stem}::{filt['name']}"
            r = results.get(key, {})
            status = r.get("status", "pending")
            if status == "done":
                rel = f"{song_stem}/{filt['name'].replace(' ', '_')}"
                cells.append(
                    f"<td class='done'>"
                    f"<a href='{rel}/clip.mp4'><img src='{rel}/keyframe.png' loading='lazy'></a>"
                    f"<div class='meta'><a href='{rel}/clip.mp4'>▶ clip</a> · <a href='{rel}/prompts.json'>prompts</a></div>"
                    f"</td>"
                )
            else:
                err = r.get("error", "")
                cells.append(f"<td class='{status}'><div class='meta'>{status}</div><div class='err'>{escape(err)[:120]}</div></td>")
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    header_cells = ["<th></th>"]
    for s in songs:
        first = s["first_line"]["text"]
        header_cells.append(f"<th scope='col'>{escape(s['stem'])}<div class='sub'>{escape(first[:50])}</div></th>")

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>POC 17 — Filter Gallery</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, sans-serif; margin: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #0003; padding: .3rem; vertical-align: top; text-align: left; }}
  th {{ background: #0001; position: sticky; top: 0; z-index: 1; }}
  th[scope=row] {{ white-space: nowrap; }}
  .status {{ font-size: 10px; opacity: .6; }}
  .cat {{ font-size: 10px; opacity: .4; font-style: italic; }}
  .sub {{ font-size: 10px; opacity: .6; font-weight: 400; }}
  td {{ width: 320px; height: 230px; }}
  td img {{ width: 100%; height: 180px; object-fit: cover; display: block; }}
  td .meta {{ font-size: 11px; margin-top: 4px; }}
  td.done {{ background: #efe; }}
  td.failed, td.pending {{ background: #fdd; }}
  td .err {{ color: #a00; font-size: 10px; }}
  a {{ text-decoration: none; }}
</style>
</head>
<body>
<h1>POC 17 — Filter Gallery</h1>
<p>{len([f for f in filters])} filters × {len(songs)} songs. Click any thumbnail to play the clip.</p>
<table>
<thead><tr>{''.join(header_cells)}</tr></thead>
<tbody>
{''.join(rows_html)}
</tbody>
</table>
</body>
</html>
"""
    (run_dir / "gallery.html").write_text(html)


# --- main --------------------------------------------------------------------

def main():
    styles = yaml.safe_load(STYLES_YAML.read_text())
    filters = [f for f in styles["filters"] if f["status"] in ("accepted", "proposed")]

    song_paths = sorted(MUSIC_DIR.glob("*.wav"))
    if not song_paths:
        print("No songs in music/.", file=sys.stderr)
        sys.exit(1)

    run_dir = make_run_dir(__file__)
    print(f"Run dir: {run_dir}")

    # Resolve first lines per song (triggers transcription as needed)
    songs: list[dict] = []
    for sp in song_paths:
        aligned_path = ensure_aligned(sp)
        aligned = json.loads(aligned_path.read_text())
        first = first_line_from_aligned(aligned)
        lyrics_text = clean_lyrics((MUSIC_DIR / f"{sp.stem}.txt").read_text())
        songs.append({
            "stem": sp.stem,
            "path": str(sp),
            "lyrics": lyrics_text,
            "first_line": first,
            "aligned_path": str(aligned_path),
        })
        print(f"  {sp.stem}: first line {first['text']!r} @ {first['start']:.2f}s")

    # Persist songs metadata
    (run_dir / "songs.json").write_text(json.dumps(
        [{k: v for k, v in s.items() if k != "lyrics"} for s in songs],
        indent=2, default=str,
    ))

    # Task list (ordered: each filter across all songs; rotates so no song waits too long)
    tasks = []
    for song in songs:
        for filt in filters:
            tasks.append((song["stem"], filt["name"]))

    # Results dict keyed by "<song>::<filter>"
    results: dict[str, dict] = {}

    start_time = time.time()
    write_progress(run_dir, tasks, results, start_time, None, False, songs, filters)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    for i, (song_stem, filter_name) in enumerate(tasks):
        key = f"{song_stem}::{filter_name}"
        filt = next(f for f in filters if f["name"] == filter_name)
        song = next(s for s in songs if s["stem"] == song_stem)

        slug = filter_name.replace(" ", "_")
        out_dir = run_dir / song_stem / slug
        clip_path = out_dir / "clip.mp4"
        if clip_path.exists():
            results[key] = {"status": "done", "cached": True}
            write_progress(run_dir, tasks, results, start_time, None, False, songs, filters)
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        write_progress(run_dir, tasks, results, start_time, (song_stem, filter_name), False, songs, filters)
        print(f"\n[{i+1}/{len(tasks)}] {song_stem} × {filter_name}")

        try:
            # Pass A
            pass_a_input = PASS_A_PROMPT.format(lyrics=song["lyrics"], filter_word=filter_name)
            t0 = time.time()
            brief_resp = client.models.generate_content(model=LLM_MODEL, contents=pass_a_input)
            brief = brief_resp.text.strip()
            pass_a_s = time.time() - t0

            # Pass B
            pass_b_input = PASS_B_PROMPT.format(
                lyrics=song["lyrics"], brief=brief, target_line=song["first_line"]["text"],
            )
            t0 = time.time()
            pb_resp = client.models.generate_content(model=LLM_MODEL, contents=pass_b_input)
            image_prompt = pb_resp.text.strip().strip('"').strip()
            pass_b_s = time.time() - t0

            # Gemini image
            t0 = time.time()
            image_bytes = gemini_image_with_retry(client, [image_prompt])
            img_s = time.time() - t0
            if image_bytes is None:
                raise RuntimeError("Gemini image failed after 3 attempts")
            keyframe_path = out_dir / "keyframe.png"
            keyframe_path.write_bytes(image_bytes)

            # LTX I2V
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
                raise RuntimeError(f"LTX failed (rc={res.returncode}, see {log_path})")

            # Persist prompts
            save_prompts(out_dir, {
                "song": song_stem,
                "filter": filter_name,
                "filter_status": filt["status"],
                "filter_category": filt.get("category"),
                "first_line": song["first_line"],
                "pass_a_input": pass_a_input,
                "pass_a_brief": brief,
                "pass_b_input": pass_b_input,
                "image_prompt": image_prompt,
                "ltx_motion_prompt": MOTION_PROMPT,
                "ltx_negative": TECH_NEGATIVE,
                "ltx_final_prompt": ltx_prompt,
                "timings_s": {
                    "pass_a": round(pass_a_s, 2),
                    "pass_b": round(pass_b_s, 2),
                    "image": round(img_s, 2),
                    "ltx": round(ltx_s, 2),
                    "total": round(pass_a_s + pass_b_s + img_s + ltx_s, 2),
                },
            })

            results[key] = {"status": "done", "cached": False,
                            "timings_s": {"pass_a": pass_a_s, "pass_b": pass_b_s,
                                          "image": img_s, "ltx": ltx_s}}
            print(f"    ✓ done in {pass_a_s+pass_b_s+img_s+ltx_s:.1f}s")
        except Exception as e:
            tb = traceback.format_exc()
            err_msg = str(e)
            (out_dir / "error.txt").write_text(f"{err_msg}\n\n{tb}")
            results[key] = {"status": "failed", "error": err_msg}
            print(f"    ✗ failed: {err_msg}", file=sys.stderr)

        # Save state + progress after every combo
        (run_dir / "run_state.json").write_text(json.dumps({
            "tasks": tasks, "results": results,
            "start_time": start_time,
        }, indent=2, default=str))
        write_progress(run_dir, tasks, results, start_time, None, False, songs, filters)

    # Final gallery
    write_gallery(run_dir, songs, filters, results)
    write_progress(run_dir, tasks, results, start_time, None, True, songs, filters)

    total_elapsed = time.time() - start_time
    done_count = sum(1 for v in results.values() if v.get("status") == "done")
    failed_count = sum(1 for v in results.values() if v.get("status") == "failed")
    print(f"\n========")
    print(f"Done: {done_count}/{len(tasks)}, failed: {failed_count}, elapsed {fmt_duration(total_elapsed)}")
    print(f"Gallery: {run_dir / 'gallery.html'}")
    print(f"Progress: {run_dir / 'progress.html'}")


if __name__ == "__main__":
    main()
