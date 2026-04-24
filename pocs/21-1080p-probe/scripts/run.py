#!/usr/bin/env python
"""POC 21 — probe LTX-2 dev-two-stage at 1920×1080 / 30 fps to find max num_frames.

Two passes: default tiling, then --tiling aggressive. Each pass increases
num_frames monotonically and stops on first failure. Live progress HTML.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional

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

WIDTH = 1920
HEIGHT = 1088  # LTX-2 requires dims divisible by 64; 1080 doesn't, 1088 does (8px letterbox)
FPS = 30

# Ascending num_frames, each satisfies `1 + 8k`
FRAME_CANDIDATES = [9, 17, 25, 33, 49, 73, 97, 121, 145, 193, 241]
# 30fps durations: 0.30 0.57 0.83 1.10 1.63 2.43 3.23 4.03 4.83 6.43 8.03

TILINGS = ["auto", "aggressive"]

IMG_MODEL = "gemini-3.1-flash-image-preview"
KEYFRAME_PROMPT = (
    "A wide cinematic charcoal illustration: a weathered stone cottage on a "
    "windswept northern English moor at dusk, heavy cloud above, a single "
    "black bird silhouette perched on a dry-stone wall in the foreground. "
    "Heavy cross-hatching, velvety blacks against raw white highlights, grainy "
    "paper texture. No people, no text. Wide 16:9 composition."
)

PROMPT = (
    "slow gentle camera settle, subtle ambient motion within the frame, "
    "wind moving through the heather, quiet continuous movement, charcoal, "
    "cinematic wide shot"
)
TECH_NEGATIVE = "blurry, low quality, worst quality, distorted, watermark, subtitle"

PEAK_MEM_RE = re.compile(r"Peak memory:\s*([\d.]+)\s*GB", re.IGNORECASE)
GEN_TIME_RE = re.compile(r"Generated in\s*(.+?)\s*\(", re.IGNORECASE)
MAX_RSS_RE = re.compile(r"^\s*(\d+)\s+maximum resident set size", re.MULTILINE)


def fmt_duration(seconds: float) -> str:
    if seconds < 60: return f"{int(seconds)} s"
    m = seconds / 60
    if m < 60: return f"{m:.1f} min"
    return f"{m/60:.2f} h"


def gemini_keyframe(client, out_path: Path, max_attempts: int = 3):
    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.models.generate_content(model=IMG_MODEL, contents=KEYFRAME_PROMPT)
        except Exception as e:
            print(f"  keyframe attempt {attempt}: exception {e}", file=sys.stderr); time.sleep(2); continue
        cands = getattr(resp, "candidates", None) or []
        if not cands: time.sleep(2); continue
        content = getattr(cands[0], "content", None)
        parts = getattr(content, "parts", None) if content else None
        if not parts: time.sleep(2); continue
        for p in parts:
            if getattr(p, "inline_data", None) is not None:
                out_path.write_bytes(p.inline_data.data)
                return True
        time.sleep(2)
    return False


def parse_ltx_log(log_text: str) -> dict:
    peak_m = PEAK_MEM_RE.search(log_text)
    gen_m = GEN_TIME_RE.search(log_text)
    # De-ANSI-escape via replace of \r segments
    return {
        "peak_memory_gb": float(peak_m.group(1)) if peak_m else None,
        "generated_in": gen_m.group(1).strip() if gen_m else None,
    }


def parse_time_file(text: str) -> dict:
    m = MAX_RSS_RE.search(text)
    rss_bytes = int(m.group(1)) if m else None
    return {"max_rss_gb": rss_bytes / 1024 / 1024 / 1024 if rss_bytes else None}


def write_progress(run_dir: Path, plan: list, results: list, current: Optional[dict],
                   start_time: float, done: bool):
    elapsed = time.time() - start_time
    completed = len(results)
    refresh = "" if done else '<meta http-equiv="refresh" content="15">'

    rows = []
    # Build status map for quick lookup
    seen = {(r["tiling"], r["num_frames"]): r for r in results}
    for item in plan:
        tile, nf = item["tiling"], item["num_frames"]
        duration = nf / FPS
        r = seen.get((tile, nf))
        status = "pending"
        wall = peak = rss = gen_in = ""
        if current and current.get("tiling") == tile and current.get("num_frames") == nf:
            status = "running"
        if r is not None:
            status = r["status"]
            wall = f"{r['wall_s']:.1f} s" if r.get("wall_s") is not None else ""
            peak = f"{r['peak_memory_gb']:.1f} GB" if r.get("peak_memory_gb") is not None else ""
            rss = f"{r['max_rss_gb']:.1f} GB" if r.get("max_rss_gb") is not None else ""
            gen_in = r.get("generated_in") or ""
        err = r.get("error", "") if r else ""
        rows.append(
            f"<tr class='{status}'>"
            f"<td>{escape(tile)}</td>"
            f"<td>{nf}</td><td>{duration:.2f} s</td>"
            f"<td>{escape(status)}</td>"
            f"<td>{escape(wall)}</td>"
            f"<td>{escape(gen_in)}</td>"
            f"<td>{escape(peak)}</td>"
            f"<td>{escape(rss)}</td>"
            f"<td class='err'>{escape(err)[:120]}</td>"
            f"</tr>"
        )

    current_html = ""
    if current and not done:
        current_html = (
            f"<div class='current'>Running: "
            f"<b>tiling={escape(current['tiling'])}, num_frames={current['num_frames']}</b> "
            f"(duration {current['num_frames']/FPS:.2f} s at 30 fps)</div>"
        )

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>POC 21 — 1080p/30fps probe</title>{refresh}
<style>
  :root{{color-scheme:light dark}}body{{font-family:-apple-system,sans-serif;margin:1.5rem;max-width:1400px}}
  .summary{{display:flex;gap:2rem;margin:1rem 0}}.summary .num{{font-size:1.5rem;font-weight:600}}
  .current{{margin:1rem 0;padding:.75rem 1rem;background:#fe8;color:#000;border-radius:6px}}
  table{{border-collapse:collapse;width:100%;font-size:13px}}
  th,td{{border:1px solid #0003;padding:.4rem .6rem;text-align:left}}
  th{{background:#0001;position:sticky;top:0}}
  tr.running{{background:#fe8}}tr.done{{background:#dfd}}tr.failed{{background:#fdd}}
  .err{{color:#a00;font-size:11px;max-width:400px}}
  .sub{{font-size:11px;opacity:.7}}
</style></head><body>
<h1>POC 21 — 1920×1080 / 30 fps max-frames probe</h1>
<div class="sub">run: {escape(run_dir.name)}</div>
<div class="summary">
  <div><div>Attempts completed</div><div class="num">{completed}/{len(plan)}</div></div>
  <div><div>Elapsed</div><div class="num">{fmt_duration(elapsed)}</div></div>
</div>
{current_html}
<table>
<thead><tr>
  <th>tiling</th><th>num_frames</th><th>duration</th><th>status</th>
  <th>wall time</th><th>LTX "Generated in"</th><th>peak mem (LTX)</th><th>max RSS (OS)</th>
  <th>error</th>
</tr></thead>
<tbody>
{''.join(rows)}
</tbody></table>
<p class="sub">Last updated: {escape(datetime.now().isoformat(timespec='seconds'))}. {'Done.' if done else 'Auto-refresh 15 s.'}</p>
</body></html>
"""
    (run_dir / "progress.html").write_text(html)


def main():
    run_dir = make_run_dir(__file__)
    print(f"Run dir: {run_dir}")

    shared_dir = run_dir / "shared"; shared_dir.mkdir(exist_ok=True)
    keyframe = shared_dir / "keyframe.png"

    print("\n=== Keyframe (Gemini) ===")
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    if not gemini_keyframe(client, keyframe):
        print("ERROR: could not generate keyframe", file=sys.stderr); sys.exit(2)
    print(f"  saved {keyframe.name} ({keyframe.stat().st_size:,} bytes)")

    # Build the full plan up-front so progress.html shows all rows with pending
    plan = []
    for tile in TILINGS:
        for nf in FRAME_CANDIDATES:
            plan.append({"tiling": tile, "num_frames": nf})

    results: list[dict] = []
    start = time.time()
    write_progress(run_dir, plan, results, None, start, False)

    attempts_dir = run_dir / "attempts"
    attempts_dir.mkdir(exist_ok=True)

    save_prompts(run_dir, {
        "keyframe_prompt": KEYFRAME_PROMPT,
        "ltx_prompt": PROMPT,
        "technical_negative": TECH_NEGATIVE,
        "resolution": f"{WIDTH}x{HEIGHT}",
        "fps": FPS,
        "frame_candidates": FRAME_CANDIDATES,
        "tilings_tested": TILINGS,
    })

    for tile in TILINGS:
        aborted = False
        for nf in FRAME_CANDIDATES:
            item = {"tiling": tile, "num_frames": nf}
            if aborted:
                results.append({**item, "status": "skipped", "error": "prior attempt in this tiling pass failed"})
                write_progress(run_dir, plan, results, None, start, False)
                continue

            print(f"\n=== tiling={tile}  num_frames={nf}  ({nf/FPS:.2f}s) ===")
            write_progress(run_dir, plan, results, item, start, False)

            attempt_dir = attempts_dir / f"{tile}_{nf:04d}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            clip_path = attempt_dir / "clip.mp4"
            log_path = attempt_dir / "ltx.log"
            time_path = attempt_dir / "time.txt"

            cmd = [
                "/usr/bin/time", "-l", "-o", str(time_path),
                "uv", "run", "mlx_video.ltx_2.generate",
                "--prompt", PROMPT,
                "--negative-prompt", TECH_NEGATIVE,
                "--seed", "42",
                "--pipeline", "dev-two-stage",
                "--model-repo", "prince-canuma/LTX-2.3-dev",
                "--text-encoder-repo", "mlx-community/gemma-3-12b-it-bf16",
                "--width", str(WIDTH), "--height", str(HEIGHT),
                "--num-frames", str(nf), "--fps", str(FPS),
                "--image", str(keyframe),
                "--image-strength", "1.0",
                "--image-frame-idx", "0",
                "--tiling", tile,
                "--output-path", str(clip_path),
            ]

            t0 = time.time()
            try:
                with log_path.open("w") as logf:
                    logf.write(f"CMD: {' '.join(cmd)}\n\n")
                    logf.flush()
                    res = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT)
                wall_s = time.time() - t0
                log_text = log_path.read_text()
                time_text = time_path.read_text() if time_path.exists() else ""
                parsed = parse_ltx_log(log_text)
                time_parsed = parse_time_file(time_text)

                if res.returncode == 0 and clip_path.exists():
                    result = {
                        **item, "status": "done",
                        "wall_s": round(wall_s, 2),
                        "peak_memory_gb": parsed["peak_memory_gb"],
                        "generated_in": parsed["generated_in"],
                        "max_rss_gb": time_parsed["max_rss_gb"],
                    }
                    print(f"    ✓ {parsed.get('generated_in') or fmt_duration(wall_s)}, "
                          f"peak={parsed.get('peak_memory_gb')} GB, RSS={time_parsed.get('max_rss_gb'):.1f} GB"
                          if time_parsed.get('max_rss_gb') else "✓ done")
                else:
                    # Failure — capture the last chunk of log for the error reason
                    tail = log_text.strip().split("\n")[-10:]
                    err_msg = "\n".join(tail)[:400]
                    result = {
                        **item, "status": "failed",
                        "wall_s": round(wall_s, 2),
                        "peak_memory_gb": parsed["peak_memory_gb"],
                        "generated_in": parsed["generated_in"],
                        "max_rss_gb": time_parsed["max_rss_gb"],
                        "error": err_msg,
                        "returncode": res.returncode,
                    }
                    print(f"    ✗ failed rc={res.returncode}; aborting tiling={tile} pass", file=sys.stderr)
                    aborted = True
            except Exception as e:
                result = {**item, "status": "failed", "error": str(e), "wall_s": round(time.time() - t0, 2)}
                print(f"    ✗ exception: {e}", file=sys.stderr)
                aborted = True

            results.append(result)
            (run_dir / "results.json").write_text(json.dumps({
                "plan": plan, "results": results,
                "width": WIDTH, "height": HEIGHT, "fps": FPS,
            }, indent=2, default=str))
            write_progress(run_dir, plan, results, None, start, False)

    write_progress(run_dir, plan, results, None, start, True)

    # Summary
    print("\n===== summary =====")
    for tile in TILINGS:
        done = [r for r in results if r["tiling"] == tile and r["status"] == "done"]
        fail = [r for r in results if r["tiling"] == tile and r["status"] == "failed"]
        if done:
            max_ok = max(done, key=lambda r: r["num_frames"])
            print(f"tiling={tile}: max OK = {max_ok['num_frames']} frames "
                  f"({max_ok['num_frames']/FPS:.2f} s), peak={max_ok.get('peak_memory_gb')} GB")
        if fail:
            first_fail = min(fail, key=lambda r: r["num_frames"])
            print(f"             first fail at {first_fail['num_frames']} frames")
    print(f"\nProgress: {run_dir / 'progress.html'}")


if __name__ == "__main__":
    main()
