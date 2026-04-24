"""LTX per-shot rendering with resume + concat + master-audio mux.

For each shot with a keyframe but no clip, run LTX. Then ffmpeg concat all
clips into a single video and mux the original song audio over the top.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REPO_ROOT = HERE.parent.parent

WIDTH = 1920
HEIGHT = 1088             # closest divisible-by-64 to 1080 (LTX constraint)
FPS = 30
SEED_BASE = 42

NEG = "blurry, low quality, worst quality, distorted, watermark, subtitle"

CAMERA_LANGUAGE = {
    "static hold": "static camera, subject held steady in frame",
    "slow push in": "slow continuous forward dolly push-in, camera moves toward subject",
    "slow pull back": "slow continuous dolly pull-back, camera retreats from subject",
    "pan left": "slow horizontal pan to the left, smooth camera motion",
    "pan right": "slow horizontal pan to the right, smooth camera motion",
    "tilt up": "slow tilt upward, smooth camera motion",
    "tilt down": "slow tilt downward, smooth camera motion",
    "orbit left": "slow orbital motion around subject to the left",
    "orbit right": "slow orbital motion around subject to the right",
    "handheld drift": "gentle handheld drift, soft natural camera motion",
    "held on detail": "camera held on fine detail, very slow drift",
}


def build_prompt(shot: dict, sb: dict, filter_word: str) -> str:
    camera = sb.get("camera_intent", "static hold")
    camera_phrase = CAMERA_LANGUAGE.get(camera, camera)
    beat = sb.get("beat", "").strip()
    subject = sb.get("subject_focus", "").strip()
    # LTX needs motion-oriented phrasing
    pieces = [
        camera_phrase + ".",
        f"Subject: {subject}." if subject else "",
        beat,
        f"Rendered in {filter_word} style, consistent throughout the clip.",
    ]
    return " ".join(p for p in pieces if p)


def run_ltx(keyframe: Path, out_mp4: Path, log: Path, prompt: str, num_frames: int, seed: int) -> bool:
    cmd = [
        "uv", "run", "mlx_video.ltx_2.generate",
        "--seed", str(seed),
        "--pipeline", "dev-two-stage",
        "--model-repo", "prince-canuma/LTX-2.3-dev",
        "--text-encoder-repo", "mlx-community/gemma-3-12b-it-bf16",
        "--width", str(WIDTH), "--height", str(HEIGHT),
        "--num-frames", str(num_frames), "--fps", str(FPS),
        "--image", str(keyframe),
        "--image-strength", "1.0",
        "--image-frame-idx", "0",
        "--negative-prompt", NEG,
        "--prompt", prompt,
        "--output-path", str(out_mp4),
    ]
    with log.open("w") as f:
        proc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    return proc.returncode == 0


def ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)]
    ).decode().strip()
    return float(out)


def align_clip(src: Path, dst: Path, target_s: float, frame_tolerance_s: float = 1.0 / 60) -> str:
    """Produce `dst` from `src` trimmed or padded to exactly `target_s` seconds.

    A: rendered > target → trim tail
    B1: rendered < target → clone last frame (tpad)
    passthrough: within one half-frame.
    Re-encodes (filters can't use stream copy). H.264 + AAC-compatible MP4.
    """
    rendered = ffprobe_duration(src)
    delta = rendered - target_s
    base_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    if delta > frame_tolerance_s:
        # A — trim
        cmd = base_cmd + [
            "-t", f"{target_s:.6f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            str(dst),
        ]
        mode = f"trim -{delta:.3f}s"
    elif delta < -frame_tolerance_s:
        # B1 — clone last frame
        pad = target_s - rendered
        cmd = base_cmd + [
            "-vf", f"tpad=stop_mode=clone:stop_duration={pad:.6f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            str(dst),
        ]
        mode = f"pad +{pad:.3f}s"
    else:
        # Passthrough re-encode (concat demuxer needs consistent codec params)
        cmd = base_cmd + [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            str(dst),
        ]
        mode = "exact"
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return mode


def concat_clips(clips: list[Path], out_path: Path, concat_list: Path) -> None:
    # ffmpeg concat demuxer requires a list file
    concat_list.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips))
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", str(out_path)],
        check=True,
    )


def mux_audio(video: Path, audio: Path, out_path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(video), "-i", str(audio),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
         str(out_path)],
        check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", required=True)
    ap.add_argument("--audio", required=True, help="original song wav")
    ap.add_argument("--shots", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--filter", dest="filter_word", required=True)
    ap.add_argument("--skip-render", action="store_true", help="only concat+mux")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    clips_dir = run_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    keyframes_dir = run_dir / "keyframes"

    shots_data = json.loads(Path(args.shots).read_text())
    shots = shots_data["shots"]
    storyboard = json.loads((run_dir / "storyboard.json").read_text())
    sb_shots = {s["index"]: s for s in storyboard.get("shots", [])}

    rendered = []
    skipped = 0
    failed = []
    for s in shots:
        idx = s["index"]
        kf = keyframes_dir / f"keyframe_{idx:03d}.png"
        clip = clips_dir / f"clip_{idx:03d}.mp4"
        if clip.exists() and clip.stat().st_size > 1000:
            rendered.append(clip)
            skipped += 1
            continue
        if not kf.exists():
            print(f"[shot {idx:3d}] no keyframe — skipping", file=sys.stderr)
            continue
        if args.skip_render:
            continue
        sb = sb_shots.get(idx, {})
        prompt = build_prompt(s, sb, args.filter_word)
        log = clips_dir / f"stdout_{idx:03d}.log"
        t0 = time.time()
        ok = run_ltx(kf, clip, log, prompt, s["num_frames"], SEED_BASE + idx)
        dt = time.time() - t0
        if ok:
            print(f"[shot {idx:3d}] clip OK ({dt:.0f}s, {s['num_frames']}f)")
            rendered.append(clip)
        else:
            print(f"[shot {idx:3d}] clip FAILED (see {log})", file=sys.stderr)
            failed.append(idx)

    print(f"\n[render summary] rendered={len(rendered) - skipped} cached={skipped} failed={len(failed)}")
    if failed:
        print(f"  failed shots: {failed}", file=sys.stderr)

    if not rendered:
        sys.exit("no clips to concat")

    # Per-clip align (A trim / B1 pad / passthrough) to its contiguous-policy
    # target duration, then concat, then mux audio.
    aligned_dir = run_dir / "aligned"
    aligned_dir.mkdir(exist_ok=True)
    print(f"\n[align] trim/pad each clip to target duration...")
    aligned_paths: list[Path] = []
    # Build an index-keyed map of shot → target duration
    target_by_idx = {s["index"]: s.get("target_duration_s", s["duration_s"]) for s in shots}
    for s in shots:
        idx = s["index"]
        src = clips_dir / f"clip_{idx:03d}.mp4"
        if not (src.exists() and src.stat().st_size > 1000):
            continue
        dst = aligned_dir / f"aligned_{idx:03d}.mp4"
        target = target_by_idx[idx]
        mode = align_clip(src, dst, target)
        aligned_paths.append(dst)
        print(f"  #{idx:3d}  target={target:.3f}s  mode={mode}")

    print(f"\n[concat] {len(aligned_paths)} aligned clips...")
    video_only = run_dir / "video_concat.mp4"
    concat_list = run_dir / "concat.txt"
    concat_clips(aligned_paths, video_only, concat_list)

    print("[mux] overlaying master audio...")
    final = run_dir / "final.mp4"
    mux_audio(video_only, Path(args.audio), final)
    print(f"\n[done] {final}")


if __name__ == "__main__":
    main()
