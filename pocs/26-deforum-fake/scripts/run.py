"""POC 26 — fake Deforum camera moves via PR #23 start+end conditioning.

Start image = POC 13 keyframe_01. End image = same content, rotated 15° and
zoomed 5%. LTX is forced to interpolate the transform frame-by-frame, which
reads visually as a slow continuous zoom+rotate camera move.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent.parent
REPO_ROOT = HERE.parent.parent

# Reuse POC 25's locked-down generator config
WIDTH = 512
HEIGHT = 320
NUM_FRAMES = 73       # 3.0 s @ 24fps, valid 1 + 8*k
FPS = 24
SEED = 42

PROMPT = (
    "slow continuous camera push-in with a gentle counter-clockwise rotation, "
    "narrator at a candlelit table, charcoal textures, grainy paper, natural "
    "domestic light, no cuts, smooth motion"
)
NEG = "blurry, low quality, worst quality, distorted, watermark, subtitle, cut, jump cut"


def make_end_image(
    start_path: Path, end_path: Path, rotate_deg: float, zoom_factor: float
) -> None:
    """End = rotate then center-crop-zoom then resize back to original.

    The zoom must be large enough to inscribe the rotated rectangle without
    black corners: for rotation θ on a w×h image, the largest axis-aligned
    inscribed rectangle has width w' = w*cos(θ) - h*sin(θ) (for w ≥ h).
    """
    src = Image.open(start_path).convert("RGB")
    w, h = src.size

    rotated = src.rotate(
        rotate_deg,
        resample=Image.BICUBIC,
        expand=False,
        fillcolor=(0, 0, 0),
    )

    new_w = int(round(w / zoom_factor))
    new_h = int(round(h / zoom_factor))
    x0 = (w - new_w) // 2
    y0 = (h - new_h) // 2
    cropped = rotated.crop((x0, y0, x0 + new_w, y0 + new_h))
    zoomed = cropped.resize((w, h), resample=Image.BICUBIC)

    zoomed.save(end_path, format="PNG")


def run_cmd(cmd: list[str], log_path: Path) -> None:
    print(f"\n$ {' '.join(cmd)}")
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


def write_view_html(run_dir: Path, meta: dict) -> None:
    rotate_deg = meta["rotate_deg"]
    zoom_factor = meta["zoom_factor"]
    zoom_pct = int(round((zoom_factor - 1) * 100))
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>POC 26 — {meta['variant']}</title>
<style>
  :root{{color-scheme:light dark}}
  body{{font-family:-apple-system,sans-serif;margin:1rem;max-width:1600px}}
  .row{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:1rem}}
  .four{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}
  .cell{{background:#0001;padding:8px;border-radius:6px}}
  .cell h2,.cell h3{{margin:0 0 6px}}
  img,video{{width:100%;display:block;background:#000}}
  .sub{{font-size:12px;color:#888}}
  pre{{background:#0002;padding:8px;border-radius:4px;font-size:12px;overflow-x:auto}}
</style></head><body>
<h1>POC 26 — {meta['variant']} (rotate {rotate_deg}°, zoom {zoom_pct}%)</h1>
<p>Same content for start and end, but end is geometrically transformed. LTX interpolates → looks like a continuous camera move.</p>

<div class="row">
  <div class="cell"><h2>Start keyframe</h2><img src="start.png"><p class="sub">--image (from POC 13)</p></div>
  <div class="cell"><h2>End keyframe (transformed)</h2><img src="end.png"><p class="sub">rotated {rotate_deg}°, zoomed {zoom_pct}%, fed as --end-image</p></div>
</div>

<div class="cell">
  <h2>Generated clip</h2>
  <video src="clip.mp4" controls preload="metadata" loop autoplay muted></video>
</div>

<h2>Frame progression</h2>
<div class="four">
  <div class="cell"><h3>frame 0</h3><img src="frame_00.png"></div>
  <div class="cell"><h3>frame {NUM_FRAMES // 3}</h3><img src="frame_24.png"></div>
  <div class="cell"><h3>frame {2 * (NUM_FRAMES // 3)}</h3><img src="frame_48.png"></div>
  <div class="cell"><h3>frame {NUM_FRAMES - 1}</h3><img src="frame_last.png"></div>
</div>

<h2>Config</h2>
<pre>{json.dumps(meta, indent=2)}</pre>
</body></html>
"""
    (run_dir / "view.html").write_text(html)


def run_variant(
    variant: str, rotate_deg: float, zoom_factor: float, start_src: Path, parent_dir: Path
) -> Path:
    run_dir = parent_dir / variant
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n### variant={variant} rotate={rotate_deg}° zoom={zoom_factor}")
    print(f"Run dir: {run_dir}")

    start_path = run_dir / "start.png"
    end_path = run_dir / "end.png"
    shutil.copy2(start_src, start_path)
    make_end_image(start_path, end_path, rotate_deg, zoom_factor)
    print(f"Wrote {start_path.name}, {end_path.name}")

    clip_path = run_dir / "clip.mp4"
    log_path = run_dir / "stdout-ltx.log"
    cmd = [
        "uv", "run", "mlx_video.ltx_2.generate",
        "--seed", str(SEED),
        "--pipeline", "dev-two-stage",
        "--model-repo", "prince-canuma/LTX-2.3-dev",
        "--text-encoder-repo", "mlx-community/gemma-3-12b-it-bf16",
        "--width", str(WIDTH), "--height", str(HEIGHT),
        "--num-frames", str(NUM_FRAMES), "--fps", str(FPS),
        "--image", str(start_path),
        "--image-strength", "1.0",
        "--image-frame-idx", "0",
        "--end-image", str(end_path),
        "--end-image-strength", "1.0",
        "--negative-prompt", NEG,
        "--prompt", PROMPT,
        "--output-path", str(clip_path),
    ]
    run_cmd(cmd, log_path)

    duration_s = NUM_FRAMES / FPS
    extract_frame(clip_path, run_dir / "frame_00.png", seek_s=None)
    extract_frame(clip_path, run_dir / "frame_24.png", seek_s=24 / FPS)
    extract_frame(clip_path, run_dir / "frame_48.png", seek_s=48 / FPS)
    extract_frame(clip_path, run_dir / "frame_last.png", seek_s=duration_s - 0.05)

    meta = {
        "variant": variant,
        "start_source": str(start_src),
        "rotate_deg": rotate_deg,
        "zoom_factor": zoom_factor,
        "prompt": PROMPT,
        "negative": NEG,
        "pipeline": "dev-two-stage",
        "seed": SEED,
        "width": WIDTH, "height": HEIGHT,
        "num_frames": NUM_FRAMES, "fps": FPS,
        "image_strength": 1.0, "end_image_strength": 1.0,
    }
    (run_dir / "prompts.json").write_text(json.dumps(meta, indent=2))
    write_view_html(run_dir, meta)
    return run_dir


def write_sweep_index(parent_dir: Path, variants: list[dict]) -> None:
    cells = ""
    for v in variants:
        pct = int(round((v["zoom_factor"] - 1) * 100))
        cells += f"""
  <div class="cell">
    <h2>{v['variant']}</h2>
    <p class="sub">rotate {v['rotate_deg']}°, zoom {pct}%</p>
    <video src="{v['variant']}/clip.mp4" controls preload="metadata" loop muted></video>
    <div class="pair">
      <div><h3>end.png (input)</h3><img src="{v['variant']}/end.png"></div>
      <div><h3>frame_last (output)</h3><img src="{v['variant']}/frame_last.png"></div>
    </div>
    <p><a href="{v['variant']}/view.html">details →</a></p>
  </div>"""
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>POC 26 sweep</title>
<style>
  :root{{color-scheme:light dark}}
  body{{font-family:-apple-system,sans-serif;margin:1rem;max-width:1800px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
  .cell{{background:#0001;padding:8px;border-radius:6px}}
  .cell h2,.cell h3{{margin:0 0 6px}}
  img,video{{width:100%;display:block;background:#000}}
  .pair{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:6px}}
  .sub{{font-size:12px;color:#888}}
</style></head><body>
<h1>POC 26 — rotate/zoom sweep</h1>
<p>Goal: find rotate/zoom combo where end.png has no black corners AND motion reads as camera, not cut.</p>
<div class="grid">{cells}
</div></body></html>
"""
    (parent_dir / "index.html").write_text(html)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--variants",
        default="subtle:4:1.13,strong:15:1.44",
        help="Comma-sep list of name:rotate_deg:zoom_factor",
    )
    args = ap.parse_args()

    poc13_latest = REPO_ROOT / "pocs" / "13-combined" / "outputs" / "latest"
    if not poc13_latest.exists():
        sys.exit(f"missing {poc13_latest}")
    start_src = (poc13_latest / "keyframe_01.png").resolve()
    if not start_src.exists():
        sys.exit(f"missing {start_src}")

    ts = time.strftime("%Y%m%d-%H%M%S")
    parent_dir = HERE / "outputs" / ts
    parent_dir.mkdir(parents=True, exist_ok=True)
    latest = HERE / "outputs" / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(ts)
    print(f"Parent dir: {parent_dir}")

    variants = []
    for spec in args.variants.split(","):
        name, rot, zoom = spec.split(":")
        variants.append(
            {"variant": name, "rotate_deg": float(rot), "zoom_factor": float(zoom)}
        )

    for v in variants:
        run_variant(v["variant"], v["rotate_deg"], v["zoom_factor"], start_src, parent_dir)

    write_sweep_index(parent_dir, variants)
    print(f"\n=== done ===\nopen {parent_dir / 'index.html'}")


if __name__ == "__main__":
    main()
