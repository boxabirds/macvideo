"""Remap archived 24fps-shot keyframes + storyboard + prompts to the new
30fps-shot indexing by max temporal overlap.

The new shot list (30fps, MAX_SHOT_S=2.4) is mostly the 24fps shot list with
longer shots split into smaller pieces. For each new shot, find the old shot
whose time span most overlaps and copy its keyframe, storyboard entry, and
image prompt to the new index.

No new Gemini calls.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    new_shots = json.loads((run_dir / "shots.json").read_text())["shots"]
    old_shots_bak = run_dir / "shots.json.24fps.bak"
    if not old_shots_bak.exists():
        sys.exit(f"missing {old_shots_bak}")
    old_shots = json.loads(old_shots_bak.read_text())["shots"]

    old_storyboard = json.loads((run_dir / "storyboard.json.24fps.bak").read_text())
    old_sb = {s["index"]: s for s in old_storyboard.get("shots", [])}
    old_prompts_path = run_dir / "image_prompts.json.24fps.bak"
    old_prompts = json.loads(old_prompts_path.read_text()) if old_prompts_path.exists() else {}

    # Copy character brief as-is (same song, same filter, same abstraction)
    brief_bak = run_dir / "character_brief.json.24fps.bak"
    if brief_bak.exists() and not (run_dir / "character_brief.json").exists():
        shutil.copy2(brief_bak, run_dir / "character_brief.json")

    # Build new keyframes dir, storyboard, image_prompts
    new_kf_dir = run_dir / "keyframes"
    new_kf_dir.mkdir(exist_ok=True)
    old_kf_dir = run_dir / "keyframes_24fps_shots"

    new_sb_shots = []
    new_prompts = {}

    reused = 0
    missing = 0
    for ns in new_shots:
        new_idx = ns["index"]
        n_start, n_end = ns["start_s"], ns["end_s"]
        # Find old shot with max overlap
        best = None
        best_ov = 0.0
        for os in old_shots:
            ov = overlap(n_start, n_end, os["start_s"], os["end_s"])
            if ov > best_ov:
                best_ov = ov
                best = os
        if best is None or best_ov <= 0:
            # No overlap — could happen at boundaries. Use nearest old shot.
            best = min(old_shots, key=lambda o: min(abs(o["start_s"] - n_start), abs(o["end_s"] - n_end)))

        old_idx = best["index"]

        # Keyframe
        old_kf = old_kf_dir / f"keyframe_{old_idx:03d}.png"
        new_kf = new_kf_dir / f"keyframe_{new_idx:03d}.png"
        if old_kf.exists():
            shutil.copy2(old_kf, new_kf)
            reused += 1
        else:
            missing += 1

        # Storyboard entry (keep old beat/camera/focus, update index + target_text)
        if old_idx in old_sb:
            osb = old_sb[old_idx]
            new_sb_shots.append({
                "index": new_idx,
                "target_text": ns["target_text"],
                "beat": osb.get("beat", ""),
                "camera_intent": osb.get("camera_intent", "static hold"),
                "subject_focus": osb.get("subject_focus", ""),
                "prev_link": osb.get("prev_link") if new_idx == 1 else None,
                "next_link": osb.get("next_link") if new_idx == len(new_shots) else None,
            })

        # Image prompt (keyed by "shot_XXX")
        old_key = f"shot_{old_idx:02d}"  # note: old format used 02d per original
        # Try both 02d and 03d key formats just in case
        ip = old_prompts.get(f"shot_{old_idx:03d}") or old_prompts.get(f"shot_{old_idx:02d}")
        if ip:
            new_prompts[f"shot_{new_idx:03d}"] = ip

    new_storyboard = {
        "sequence_arc": old_storyboard.get("sequence_arc", ""),
        "shots": new_sb_shots,
    }
    (run_dir / "storyboard.json").write_text(json.dumps(new_storyboard, indent=2))
    (run_dir / "image_prompts.json").write_text(json.dumps(new_prompts, indent=2))

    print(f"[{run_dir.name}] new_shots={len(new_shots)} keyframes_reused={reused} missing={missing}")
    print(f"  storyboard entries: {len(new_sb_shots)}, prompts: {len(new_prompts)}")


if __name__ == "__main__":
    main()
