#!/usr/bin/env python
"""POC 24 — densify long shots with cuts at strong drum onsets."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))
from pocs._lib.poc_helpers import make_run_dir  # noqa: E402
from pocs._lib import audio_features  # noqa: E402

DEFAULT_PLAN_PATH = REPO_ROOT / "pocs" / "15-gap-interpolation" / "outputs" / "latest" / "shots.json"
DEFAULT_SONG = "my-little-blackbird"
MIN_LONG_S = 2.0         # only densify shots at least this long
MIN_SPLIT_GAP_S = 0.4    # don't split within this distance of an endpoint
MAX_SPLITS_PER_SHOT = 3
STRONG_PERCENTILE = 75.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH)
    ap.add_argument("--song", default=DEFAULT_SONG)
    ap.add_argument("--features", type=Path, default=None)
    ap.add_argument("--min-long-s", type=float, default=MIN_LONG_S)
    ap.add_argument("--min-split-gap-s", type=float, default=MIN_SPLIT_GAP_S)
    ap.add_argument("--max-splits-per-shot", type=int, default=MAX_SPLITS_PER_SHOT)
    ap.add_argument("--percentile", type=float, default=STRONG_PERCENTILE)
    args = ap.parse_args()

    if not args.plan.exists():
        print(f"ERROR: plan not found at {args.plan}", file=sys.stderr); sys.exit(1)
    if args.features is None:
        poc22_latest = REPO_ROOT / "pocs" / "22-audio-timeline" / "outputs" / "latest"
        args.features = poc22_latest / f"{args.song}_features.json"
    if not args.features.exists():
        print(f"ERROR: features not found at {args.features}", file=sys.stderr); sys.exit(1)

    run_dir = make_run_dir(__file__, tag=f"{args.song}-dens")
    print(f"Run dir: {run_dir}")

    feats_bundle = json.loads(args.features.read_text())
    feats = feats_bundle.get("features", feats_bundle)
    strong = audio_features.strong_drum_onsets(feats, percentile=args.percentile)
    print(f"Strong drum onsets (≥ {args.percentile:.0f}th pctl): {len(strong)}")

    plan = json.loads(args.plan.read_text())

    def get_start(s): return float(s.get("start_t") or s.get("clip_start_t") or s.get("line_start_t") or 0.0)
    def get_end(s):   return float(s.get("end_t")   or s.get("clip_end_t")   or s.get("line_end_t") or 0.0)

    new_plan = []
    report_rows = []

    for i, shot in enumerate(plan):
        s0 = get_start(shot)
        s1 = get_end(shot)
        dur = s1 - s0
        if dur < args.min_long_s:
            new_plan.append(shot)
            report_rows.append({"shot": i, "action": "passthrough", "reason": f"duration {dur:.2f}s < {args.min_long_s}s"})
            continue

        # Candidate splits inside the shot, excluding endpoints
        inside = [t for t in strong
                  if (t - s0) >= args.min_split_gap_s and (s1 - t) >= args.min_split_gap_s]
        if not inside:
            new_plan.append(shot)
            report_rows.append({"shot": i, "action": "passthrough", "reason": "no qualifying onsets inside"})
            continue
        if len(inside) > args.max_splits_per_shot:
            # Keep the highest-strength ones
            strengths = feats.get("drum_onset_strengths", [])
            times = feats.get("drum_onsets_s", [])
            strength_map = dict(zip(times, strengths))
            inside.sort(key=lambda t: strength_map.get(t, 0), reverse=True)
            inside = sorted(inside[: args.max_splits_per_shot])

        # Build split boundaries
        bounds = [s0] + sorted(inside) + [s1]
        split_count = len(bounds) - 1
        for k in range(split_count):
            child = copy.deepcopy(shot)
            child_start = round(bounds[k], 3)
            child_end = round(bounds[k + 1], 3)
            child_dur = child_end - child_start
            child["start_t"] = child_start
            child["end_t"] = child_end
            child["duration_s"] = round(child_dur, 3)
            if "num_frames" in child:
                fps = child.get("fps", 24)
                raw = max(1, round(child_dur * fps))
                child["num_frames"] = max(1, ((raw - 1) // 8) * 8 + 1)
                child["actual_clip_duration_s"] = round(child["num_frames"] / fps, 3)
            child["parent_shot_index"] = i
            child["split_index"] = k
            child["split_total"] = split_count
            new_plan.append(child)
        report_rows.append({
            "shot": i, "action": "split", "splits": split_count,
            "at_onsets": [round(t, 3) for t in inside],
            "original_range": [round(s0, 3), round(s1, 3)],
        })

    (run_dir / "densified_shots.json").write_text(json.dumps(new_plan, indent=2, default=str))
    (run_dir / "densify_log.json").write_text(json.dumps(report_rows, indent=2))

    lines = [f"# POC 24 densify report — {args.song}", ""]
    lines.append(f"- Source plan: `{args.plan}`  ({len(plan)} shots)")
    lines.append(f"- Features:     `{args.features}`")
    lines.append(f"- Min shot duration to consider: {args.min_long_s} s")
    lines.append(f"- Min split gap from endpoints:  {args.min_split_gap_s} s")
    lines.append(f"- Max splits per shot:           {args.max_splits_per_shot}")
    lines.append(f"- Strong-onset percentile:       {args.percentile}")
    lines.append("")
    for r in report_rows:
        if r["action"] == "passthrough":
            lines.append(f"- Shot {r['shot']}: passthrough ({r['reason']})")
        else:
            lines.append(f"- Shot {r['shot']}: split into {r['splits']} at onsets {r['at_onsets']} "
                         f"(original range {r['original_range']})")
    lines.append("")
    lines.append(f"**Result:** {len(new_plan)} shots (was {len(plan)}).")
    (run_dir / "densify_report.md").write_text("\n".join(lines))

    print(f"\n{len(plan)} shots → {len(new_plan)} shots (+{len(new_plan)-len(plan)} from splits)")
    print(f"  {run_dir / 'densified_shots.json'}")
    print(f"  {run_dir / 'densify_report.md'}")


if __name__ == "__main__":
    main()
