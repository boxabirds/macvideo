"""POC 28 v2 LTX sweep — geometric zoom + content morph variants."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

WIDTH = 512
HEIGHT = 320
NUM_FRAMES = 145
FPS = 24
SEED = 42

PROMPT = (
    "Continuous slow forward push-in camera motion, the camera dollies toward "
    "the subject, no cuts. Kitchen interior dissolves; misty open field at "
    "dawn emerges; narrator and blackbird morph with the motion. Charcoal on "
    "heavy-tooth paper, dense cross-hatching, smooth continuous motion."
)
NEG = (
    "blurry, low quality, worst quality, distorted, watermark, subtitle, "
    "cut, jump cut, hard transition, scene change, fade to black"
)

VARIANTS = ["geo_window", "geo_bird", "geo_narrator"]


def run_cmd(cmd: list[str], log_path: Path) -> None:
    with log_path.open("w") as f:
        proc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        tail = log_path.read_text().splitlines()[-40:]
        print("\n".join(tail))
        sys.exit(f"FAILED (see {log_path})")


def extract_frame(video: Path, out_png: Path, seek_s: float | None = None) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if seek_s is not None:
        cmd += ["-ss", f"{seek_s:.3f}"]
    cmd += ["-i", str(video), "-vframes", "1", str(out_png)]
    subprocess.run(cmd, check=True)


def main() -> None:
    kf_dir = HERE / "keyframes_v2"
    start = kf_dir / "start.png"
    if not start.exists():
        sys.exit("run gen_geo_ends.py first")

    ts = time.strftime("%Y%m%d-%H%M%S")
    parent_dir = HERE / "outputs" / f"v2-{ts}"
    parent_dir.mkdir(parents=True, exist_ok=True)
    latest = HERE / "outputs" / "latest-v2"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(f"v2-{ts}")
    print(f"Parent dir: {parent_dir}")

    shutil.copy2(start, parent_dir / "start.png")

    for name in VARIANTS:
        print(f"\n### {name}")
        vdir = parent_dir / name
        vdir.mkdir(parents=True, exist_ok=True)
        end = kf_dir / f"end_{name}.png"
        zoomed = kf_dir / f"{name}_zoomed_crop.png"
        if not end.exists():
            print(f"  missing {end}, skipping")
            continue
        shutil.copy2(end, vdir / "end.png")
        if zoomed.exists():
            shutil.copy2(zoomed, vdir / "zoomed_crop.png")

        clip_path = vdir / "clip.mp4"
        log_path = vdir / "stdout-ltx.log"
        cmd = [
            "uv", "run", "mlx_video.ltx_2.generate",
            "--seed", str(SEED),
            "--pipeline", "dev-two-stage",
            "--model-repo", "prince-canuma/LTX-2.3-dev",
            "--text-encoder-repo", "mlx-community/gemma-3-12b-it-bf16",
            "--width", str(WIDTH), "--height", str(HEIGHT),
            "--num-frames", str(NUM_FRAMES), "--fps", str(FPS),
            "--image", str(start),
            "--image-strength", "1.0",
            "--image-frame-idx", "0",
            "--end-image", str(end),
            "--end-image-strength", "1.0",
            "--negative-prompt", NEG,
            "--prompt", PROMPT,
            "--output-path", str(clip_path),
        ]
        run_cmd(cmd, log_path)
        duration_s = NUM_FRAMES / FPS
        for i in range(6):
            frac = i / 5
            seek = None if i == 0 else min(frac * duration_s, duration_s - 0.05)
            extract_frame(clip_path, vdir / f"frame_{i}.png", seek_s=seek)

    # Index HTML
    rows = ""
    for name in VARIANTS:
        frames_html = "".join(
            f'<img src="{name}/frame_{i}.png" title="frame {i}">'
            for i in range(6)
        )
        rows += f"""
  <div class="variant">
    <h2>{name}</h2>
    <div class="trio">
      <div><h3>zoomed crop (PIL, 2x)</h3><img src="{name}/zoomed_crop.png"></div>
      <div><h3>end.png (Gemini morph)</h3><img src="{name}/end.png"></div>
      <div><h3>clip.mp4</h3><video src="{name}/clip.mp4" controls preload="metadata" loop muted></video></div>
    </div>
    <div class="strip">{frames_html}</div>
  </div>"""
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>POC 28 v2 — geometric zoom + morph</title>
<style>
  :root{{color-scheme:light dark}}
  body{{font-family:-apple-system,sans-serif;margin:1rem;max-width:1800px}}
  .intro{{background:#0001;padding:10px;border-radius:6px;margin-bottom:1rem}}
  .intro img{{max-width:400px;display:block}}
  .variant{{background:#0001;padding:12px;border-radius:6px;margin-bottom:1.5rem}}
  .variant h2{{margin:0 0 8px}}
  .trio{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:8px}}
  .trio img,.trio video{{width:100%;background:#000;border-radius:4px}}
  .strip{{display:grid;grid-template-columns:repeat(6,1fr);gap:4px}}
  .strip img{{width:100%;background:#000;border-radius:2px}}
  pre{{background:#0002;padding:8px;border-radius:4px;font-size:12px;overflow-x:auto;white-space:pre-wrap}}
</style></head><body>
<h1>POC 28 v2 — geometric zoom (PIL) + content morph (Gemini)</h1>
<div class="intro">
<p><b>Hypothesis:</b> for LTX to interpret a transition as a real camera zoom
(not a crossfade), the end frame must be GEOMETRICALLY derived from the start
(a zoomed crop) — not just conceptually "where the zoom ends up".</p>
<h3>Start</h3><img src="start.png">
<h3>LTX prompt (identical for all 3):</h3><pre>{PROMPT}</pre>
</div>
{rows}
</body></html>
"""
    (parent_dir / "index.html").write_text(html)

    (parent_dir / "meta.json").write_text(json.dumps({
        "prompt": PROMPT, "negative": NEG,
        "pipeline": "dev-two-stage", "seed": SEED,
        "width": WIDTH, "height": HEIGHT,
        "num_frames": NUM_FRAMES, "fps": FPS,
    }, indent=2))

    print(f"\n=== done ===\nopen {parent_dir / 'index.html'}")


if __name__ == "__main__":
    main()
