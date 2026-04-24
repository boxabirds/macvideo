#!/usr/bin/env python
"""POC 23 — snap a shot plan's cut boundaries to the nearest musical event
within ±100 ms. Planner-only; no LTX."""

from __future__ import annotations

import argparse
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
TOLERANCE_S = 0.100  # ±100 ms
STRONG_PERCENTILE = 75.0


def nearest_event(t: float, sources: list[tuple[str, list[float]]], tolerance: float):
    """sources is [(label, [events])]. Returns (new_t, event_type, delta) or (t, None, 0)."""
    best = None
    for label, events in sources:
        if not events:
            continue
        nearest = min(events, key=lambda e: abs(e - t))
        delta = nearest - t
        if abs(delta) <= tolerance:
            if best is None or abs(delta) < abs(best[2]):
                best = (float(nearest), label, float(delta))
    if best is None:
        return t, None, 0.0
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH,
                    help="Source shot plan JSON (default: POC 15 latest shots.json)")
    ap.add_argument("--song", default=DEFAULT_SONG,
                    help="Song stem used to locate audio features from POC 22 latest")
    ap.add_argument("--features", type=Path, default=None,
                    help="Explicit features JSON path (overrides POC 22 latest lookup)")
    ap.add_argument("--tolerance-ms", type=int, default=100,
                    help="Snap tolerance in milliseconds (default 100)")
    args = ap.parse_args()

    if not args.plan.exists():
        print(f"ERROR: plan not found at {args.plan}", file=sys.stderr)
        sys.exit(1)

    if args.features is None:
        poc22_latest = REPO_ROOT / "pocs" / "22-audio-timeline" / "outputs" / "latest"
        if not poc22_latest.exists():
            print("ERROR: POC 22 output missing; run POC 22 first or pass --features", file=sys.stderr)
            sys.exit(1)
        args.features = poc22_latest / f"{args.song}_features.json"
    if not args.features.exists():
        print(f"ERROR: features not found at {args.features}", file=sys.stderr)
        sys.exit(1)

    tolerance_s = args.tolerance_ms / 1000.0
    run_dir = make_run_dir(__file__, tag=f"{args.song}-{args.tolerance_ms}ms")
    print(f"Run dir: {run_dir}")
    print(f"Plan:     {args.plan}")
    print(f"Features: {args.features}")
    print(f"Tolerance: ±{args.tolerance_ms} ms")

    feats_bundle = json.loads(args.features.read_text())
    feats = feats_bundle.get("features", feats_bundle)  # tolerate both shapes

    strong_drums = audio_features.strong_drum_onsets(feats, percentile=STRONG_PERCENTILE)
    sources = [
        ("strong_drum_onset", strong_drums),
        ("beat", feats.get("beats_s", [])),
        ("section_boundary", feats.get("section_boundaries_s", [])),
    ]
    print(f"Events: {len(strong_drums)} strong drum onsets · "
          f"{len(feats.get('beats_s', []))} beats · "
          f"{len(feats.get('section_boundaries_s', []))} sections")

    plan = json.loads(args.plan.read_text())
    # Plan is a list of shot dicts with start_t/end_t style keys
    # Handle multiple schemas
    def get_start(s):
        return float(s.get("start_t") or s.get("clip_start_t") or s.get("line_start_t") or 0.0)
    def get_end(s):
        return float(s.get("end_t") or s.get("clip_end_t") or s.get("line_end_t") or 0.0)
    def set_start(s, v): s["start_t"] = round(float(v), 3)
    def set_end(s, v): s["end_t"] = round(float(v), 3)

    snap_log = []
    snapped_plan = []
    for i, shot in enumerate(plan):
        new_shot = dict(shot)
        orig_start = get_start(shot)
        orig_end = get_end(shot)

        # Snap end (= start of next shot). First shot's start is usually the audio start;
        # snap it too for completeness, but it's usually already at a natural boundary.
        new_start, start_type, start_delta = nearest_event(orig_start, sources, tolerance_s)
        new_end, end_type, end_delta = nearest_event(orig_end, sources, tolerance_s)

        set_start(new_shot, new_start)
        set_end(new_shot, new_end)

        # Recompute num_frames if present
        if "num_frames" in new_shot and "fps" in feats_bundle:
            pass  # num_frames belongs to shot; derive below

        dur = new_end - new_start
        if "num_frames" in shot:
            fps = shot.get("fps", 24)
            raw_frames = round(dur * fps)
            new_shot["num_frames"] = max(1, ((raw_frames - 1) // 8) * 8 + 1)
            new_shot["actual_clip_duration_s"] = round(new_shot["num_frames"] / fps, 3)
        new_shot["duration_s"] = round(dur, 3)

        snap_log.append({
            "shot_index": i,
            "start": {"from": orig_start, "to": new_start, "delta_ms": round(start_delta * 1000, 1),
                      "snapped_to": start_type},
            "end": {"from": orig_end, "to": new_end, "delta_ms": round(end_delta * 1000, 1),
                    "snapped_to": end_type},
        })
        snapped_plan.append(new_shot)

    # Fix adjacency: if shot i's end got snapped to X but shot i+1's start snapped to Y (Y != X),
    # prefer the later one to avoid overlaps, or average. Simpler: force shot i+1 start = shot i end.
    for i in range(len(snapped_plan) - 1):
        snapped_plan[i + 1]["start_t"] = snapped_plan[i]["end_t"]
        # recompute duration
        dur = float(snapped_plan[i + 1].get("end_t", 0)) - float(snapped_plan[i + 1]["start_t"])
        snapped_plan[i + 1]["duration_s"] = round(dur, 3)
        if "num_frames" in snapped_plan[i + 1]:
            fps = snapped_plan[i + 1].get("fps", 24)
            raw_frames = max(1, round(dur * fps))
            snapped_plan[i + 1]["num_frames"] = max(1, ((raw_frames - 1) // 8) * 8 + 1)
            snapped_plan[i + 1]["actual_clip_duration_s"] = round(snapped_plan[i + 1]["num_frames"] / fps, 3)

    (run_dir / "snapped_shots.json").write_text(json.dumps(snapped_plan, indent=2, default=str))
    (run_dir / "snap_log.json").write_text(json.dumps(snap_log, indent=2))

    # Human-readable report
    lines = [f"# POC 23 snap report — {args.song}", ""]
    lines.append(f"- Source plan: `{args.plan}`")
    lines.append(f"- Features:     `{args.features}`")
    lines.append(f"- Tolerance:    ±{args.tolerance_ms} ms")
    lines.append(f"- Events available: {len(strong_drums)} strong drum onsets / "
                 f"{len(feats.get('beats_s', []))} beats / "
                 f"{len(feats.get('section_boundaries_s', []))} section bounds")
    lines.append("")
    n_snapped = 0
    for entry in snap_log:
        i = entry["shot_index"]
        lines.append(f"## Shot {i}")
        for side in ("start", "end"):
            d = entry[side]
            t = d["snapped_to"]
            if t is None:
                lines.append(f"- {side}: no event within tolerance (stays at {d['from']:.3f} s)")
            else:
                n_snapped += 1
                lines.append(f"- {side}: {d['from']:.3f} → {d['to']:.3f} s  "
                             f"({d['delta_ms']:+.1f} ms, {t})")
    lines.append("")
    lines.append(f"**Snapped:** {n_snapped} boundaries across {len(plan)} shots.")
    (run_dir / "snap_report.md").write_text("\n".join(lines))

    print(f"\nSnapped {n_snapped} boundaries; wrote:")
    print(f"  {run_dir / 'snapped_shots.json'}")
    print(f"  {run_dir / 'snap_log.json'}")
    print(f"  {run_dir / 'snap_report.md'}")


if __name__ == "__main__":
    main()
