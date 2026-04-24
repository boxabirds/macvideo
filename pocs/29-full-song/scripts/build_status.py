"""Generate a status.json for the live status.html viewer.

For each of the 3 songs, report:
- per-shot: index, kind, target_text, start_s, end_s, duration_s, num_frames,
  has_keyframe, has_clip, clip_mtime, clip_render_s (if derivable)
- aggregate: clips done / total, frames done / total, min/max/avg per-frame s,
  per-song + overall ETA at the observed rate
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent

SONGS = [
    {"slug": "my-little-blackbird", "filter": "stained glass"},
    {"slug": "chronophobia",        "filter": "cyanotype"},
    {"slug": "busy-invisible",      "filter": "papercut"},
]


def analyse_song(slug: str, filter_word: str) -> dict:
    song_dir = HERE / "outputs" / slug
    shots_path = song_dir / "shots.json"
    if not shots_path.exists():
        return {"slug": slug, "error": "no shots.json"}
    shots_data = json.loads(shots_path.read_text())
    shots = shots_data["shots"]

    sb_path = song_dir / "storyboard.json"
    sb = json.loads(sb_path.read_text()) if sb_path.exists() else {"shots": []}
    sb_by_idx = {s["index"]: s for s in sb.get("shots", [])}

    # Sort clip files by mtime to derive render timings
    clips_dir = song_dir / "clips"
    kf_dir = song_dir / "keyframes"

    mtimes: list[tuple[int, float, float]] = []  # (idx, mtime, file_size)
    for s in shots:
        idx = s["index"]
        clip_path = clips_dir / f"clip_{idx:03d}.mp4"
        if clip_path.exists() and clip_path.stat().st_size > 1000:
            mtimes.append((idx, clip_path.stat().st_mtime, clip_path.stat().st_size))

    mtimes.sort(key=lambda t: t[1])

    # Derive per-clip render duration by mtime delta with the preceding clip.
    # First clip: estimate from its own mtime vs the second clip's (symmetric fallback).
    clip_render_s: dict[int, float] = {}
    for i, (idx, mt, _sz) in enumerate(mtimes):
        if i == 0:
            # No anchor; leave unknown
            continue
        prev_mt = mtimes[i - 1][1]
        clip_render_s[idx] = round(mt - prev_mt, 2)

    # Per-shot records
    shot_records = []
    for s in shots:
        idx = s["index"]
        clip_path = clips_dir / f"clip_{idx:03d}.mp4"
        kf_path = kf_dir / f"keyframe_{idx:03d}.png"
        has_clip = clip_path.exists() and clip_path.stat().st_size > 1000
        has_kf = kf_path.exists()
        rec = {
            "index": idx,
            "kind": s["kind"],
            "target_text": s["target_text"],
            "start_s": s["start_s"],
            "end_s": s["end_s"],
            "duration_s": s["duration_s"],
            "num_frames": s["num_frames"],
            "has_clip": has_clip,
            "has_keyframe": has_kf,
            "camera_intent": sb_by_idx.get(idx, {}).get("camera_intent"),
            "beat": sb_by_idx.get(idx, {}).get("beat"),
            "subject_focus": sb_by_idx.get(idx, {}).get("subject_focus"),
        }
        if has_clip:
            rec["clip_mtime"] = clip_path.stat().st_mtime
            rec["clip_size"] = clip_path.stat().st_size
            if idx in clip_render_s:
                rec["clip_render_s"] = clip_render_s[idx]
                rec["s_per_frame"] = round(clip_render_s[idx] / s["num_frames"], 3)
        shot_records.append(rec)

    # Aggregate stats
    rendered_frames = sum(s["num_frames"] for s in shots
                          if (clips_dir / f"clip_{s['index']:03d}.mp4").exists()
                          and (clips_dir / f"clip_{s['index']:03d}.mp4").stat().st_size > 1000)
    total_frames = sum(s["num_frames"] for s in shots)

    # Per-frame render rate from derived durations (skip first clip, no baseline)
    per_frame_rates = []
    for s in shots:
        rec = shot_records[s["index"] - 1]
        if "s_per_frame" in rec:
            per_frame_rates.append(rec["s_per_frame"])

    if per_frame_rates:
        min_spf = min(per_frame_rates)
        max_spf = max(per_frame_rates)
        avg_spf = sum(per_frame_rates) / len(per_frame_rates)
    else:
        min_spf = max_spf = avg_spf = None

    remaining_frames = total_frames - rendered_frames
    eta_s = remaining_frames * avg_spf if avg_spf else None

    # Currently rendering? Check for a *.log newer than any clip
    in_progress_idx = None
    logs = sorted(clips_dir.glob("stdout_*.log"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    if logs:
        newest_log = logs[0]
        try:
            idx = int(newest_log.stem.split("_")[1])
            clip_for = clips_dir / f"clip_{idx:03d}.mp4"
            if not (clip_for.exists() and clip_for.stat().st_size > 1000):
                in_progress_idx = idx
                in_progress_log_mtime = newest_log.stat().st_mtime
        except Exception:
            pass

    return {
        "slug": slug,
        "filter": filter_word,
        "duration_s": shots_data.get("duration_s"),
        "total_covered_s": shots_data.get("total_covered_s"),
        "fps": shots_data.get("fps", 30),
        "shot_count": len(shots),
        "rendered_clip_count": sum(1 for r in shot_records if r["has_clip"]),
        "rendered_frames": rendered_frames,
        "total_frames": total_frames,
        "percent_done": round(100 * rendered_frames / max(total_frames, 1), 1),
        "min_s_per_frame": round(min_spf, 2) if min_spf else None,
        "max_s_per_frame": round(max_spf, 2) if max_spf else None,
        "avg_s_per_frame": round(avg_spf, 2) if avg_spf else None,
        "remaining_frames": remaining_frames,
        "eta_s": round(eta_s) if eta_s else None,
        "in_progress_idx": in_progress_idx,
        "in_progress_log_mtime": (
            logs[0].stat().st_mtime if logs and in_progress_idx else None
        ),
        "shots": shot_records,
    }


def main() -> None:
    data = {
        "generated_at": time.time(),
        "generated_at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "render_resolution": "1920x1088",
        "fps": 30,
        "songs": [analyse_song(s["slug"], s["filter"]) for s in SONGS],
    }
    # ETA aggregate
    total_remaining = sum(s.get("remaining_frames", 0) or 0 for s in data["songs"])
    rates = [s.get("avg_s_per_frame") for s in data["songs"] if s.get("avg_s_per_frame")]
    avg_rate = sum(rates) / len(rates) if rates else None
    data["overall_remaining_frames"] = total_remaining
    data["overall_eta_s"] = round(total_remaining * avg_rate) if avg_rate else None

    out = HERE / "outputs" / "status.json"
    out.write_text(json.dumps(data, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
