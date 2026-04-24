"""POC 27 — emerge, don't cut. 4 prompt-engineering variants with same start+end.

Start = kitchen-table narrator-with-bird. End = narrator alone in misty field.
Same seed, same frames. Vary only the prompt to test whether trajectory
prompting influences how LTX morphs from A to B.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REPO_ROOT = HERE.parent.parent

WIDTH = 512
HEIGHT = 320
NUM_FRAMES = 145        # ~6s @ 24fps, valid 1 + 8*k
FPS = 24
SEED = 42

NEG = (
    "blurry, low quality, worst quality, distorted, watermark, subtitle, "
    "cut, jump cut, hard transition, scene change, fade to black"
)

VARIANTS = [
    {
        "name": "a_end_only",
        "label": "(a) end-only — describe only destination",
        "prompt": (
            "The narrator stands alone in an open misty field at dawn. "
            "Charcoal style, heavy-tooth paper, soft grainy mid-tones."
        ),
    },
    {
        "name": "b_start_only",
        "label": "(b) start-only — describe only origin",
        "prompt": (
            "The narrator sits at a kitchen table with a blackbird perched "
            "nearby. Charcoal style, heavy-tooth paper, soft grainy mid-tones."
        ),
    },
    {
        "name": "c_causal_bridge",
        "label": "(c) causal bridge — A causes B",
        "prompt": (
            "As the blackbird lifts off from the table and flies out through "
            "the window, the kitchen walls dissolve into an open misty field "
            "at dawn, and the narrator walks forward out of the interior into "
            "the landscape. Charcoal style, heavy-tooth paper, continuous "
            "motion, no cuts."
        ),
    },
    {
        "name": "d_material_bridge",
        "label": "(d) material metamorphosis + bridging element",
        "prompt": (
            "The chalky steam rising from the teacup thickens and swirls "
            "outward until it becomes dawn mist; its curls reform as distant "
            "charcoal-smudged hills on the horizon; the narrator walks forward "
            "through the thickening mist as the kitchen walls fade into open "
            "field; the blackbird's silhouette disperses into scattered ink "
            "particles carried off by the wind. Charcoal on heavy-tooth paper, "
            "continuous camera motion, material transformation, no cuts."
        ),
    },
]


def run_cmd(cmd: list[str], log_path: Path) -> None:
    print(f"\n$ {' '.join(cmd[:6])} ... (full log: {log_path})")
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


def run_variant(variant: dict, start: Path, end: Path, parent_dir: Path) -> dict:
    vdir = parent_dir / variant["name"]
    vdir.mkdir(parents=True, exist_ok=True)
    print(f"\n### {variant['name']} — {variant['label']}")

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
        "--prompt", variant["prompt"],
        "--output-path", str(clip_path),
    ]
    run_cmd(cmd, log_path)

    duration_s = NUM_FRAMES / FPS
    # Extract 6 evenly-spaced frames for trajectory inspection
    sample_count = 6
    for i in range(sample_count):
        frac = i / (sample_count - 1)
        seek = None if i == 0 else min(frac * duration_s, duration_s - 0.05)
        extract_frame(clip_path, vdir / f"frame_{i}.png", seek_s=seek)

    meta = {
        "name": variant["name"],
        "label": variant["label"],
        "prompt": variant["prompt"],
        "negative": NEG,
        "pipeline": "dev-two-stage",
        "seed": SEED,
        "width": WIDTH, "height": HEIGHT,
        "num_frames": NUM_FRAMES, "fps": FPS,
    }
    (vdir / "prompts.json").write_text(json.dumps(meta, indent=2))
    return meta


def write_index(parent_dir: Path, start: Path, end: Path, metas: list[dict]) -> None:
    rows = ""
    for m in metas:
        name = m["name"]
        frames_html = "".join(
            f'<img src="{name}/frame_{i}.png" title="frame {i}">'
            for i in range(6)
        )
        rows += f"""
  <div class="variant">
    <h2>{m['label']}</h2>
    <p class="prompt">{m['prompt']}</p>
    <video src="{name}/clip.mp4" controls preload="metadata" loop muted></video>
    <div class="strip">{frames_html}</div>
  </div>"""
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>POC 27 — emerge, don't cut</title>
<style>
  :root{{color-scheme:light dark}}
  body{{font-family:-apple-system,sans-serif;margin:1rem;max-width:1800px}}
  .endpoints{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:1.5rem}}
  .endpoints img{{width:100%;background:#000;border-radius:4px}}
  .variant{{background:#0001;padding:12px;border-radius:6px;margin-bottom:1.5rem}}
  .variant h2{{margin:0 0 4px}}
  .prompt{{font-size:13px;color:#888;margin:0 0 8px;font-style:italic}}
  video{{width:100%;max-width:900px;display:block;background:#000;margin-bottom:8px}}
  .strip{{display:grid;grid-template-columns:repeat(6,1fr);gap:4px}}
  .strip img{{width:100%;background:#000;border-radius:2px}}
</style></head><body>
<h1>POC 27 — emerge, don't cut</h1>
<p>Same start, same end, same seed. Only the prompt changes. Looking for: does the content morph continuously, or does LTX jump-cut mid-clip?</p>

<div class="endpoints">
  <div><h3>Start (frame 0)</h3><img src="start.png"></div>
  <div><h3>End (frame {NUM_FRAMES - 1})</h3><img src="end.png"></div>
</div>

{rows}
</body></html>
"""
    (parent_dir / "index.html").write_text(html)


def main() -> None:
    keyframes = HERE / "keyframes"
    start = keyframes / "start_table.png"
    end = keyframes / "end_field.png"
    for p in (start, end):
        if not p.exists():
            sys.exit(f"missing {p}; run gen_end.py first")

    ts = time.strftime("%Y%m%d-%H%M%S")
    parent_dir = HERE / "outputs" / ts
    parent_dir.mkdir(parents=True, exist_ok=True)
    latest = HERE / "outputs" / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(ts)
    print(f"Parent dir: {parent_dir}")

    shutil.copy2(start, parent_dir / "start.png")
    shutil.copy2(end, parent_dir / "end.png")

    metas = []
    for v in VARIANTS:
        metas.append(run_variant(v, start, end, parent_dir))

    write_index(parent_dir, start, end, metas)
    print(f"\n=== done ===\nopen {parent_dir / 'index.html'}")


if __name__ == "__main__":
    main()
