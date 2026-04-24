#!/usr/bin/env python
"""POC 22 — per-song audio feature timeline visualiser."""

from __future__ import annotations

import json
import sys
import time
from html import escape
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))
from pocs._lib.poc_helpers import make_run_dir  # noqa: E402
from pocs._lib import audio_features  # noqa: E402

MUSIC_DIR = REPO_ROOT / "music"
STEMS_CACHE = REPO_ROOT / "pocs" / "17-filter-gallery" / "cache"
POC7_ALIGNED_FALLBACK = REPO_ROOT / "pocs" / "07-whisperx" / "outputs" / "aligned.json"


def load_aligned(song_stem: str) -> dict:
    p = STEMS_CACHE / song_stem / "aligned.json"
    if not p.exists() and song_stem == "my-little-blackbird":
        p = POC7_ALIGNED_FALLBACK
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def plot_timeline(song: str, features: dict, lines: list, out_path: Path) -> None:
    """Render the 4-panel figure."""
    duration = features["duration_s"]

    fig, axes = plt.subplots(4, 1, figsize=(22, 10), sharex=True,
                             gridspec_kw={"height_ratios": [1.6, 1, 1, 1.2]})
    fig.suptitle(f"{song} — audio feature timeline", fontsize=13)

    # Panel 0: "waveform" proxy (onset strength) + beats + lyrics
    ax = axes[0]
    if features.get("onset_strength"):
        ax.plot(features["onset_strength_times_s"], features["onset_strength"],
                color="#888", linewidth=0.6, alpha=0.8, label="spectral novelty")
    for t in features.get("beats_s", []):
        ax.axvline(t, color="#aaa", alpha=0.35, linewidth=0.4)
    # Lyric lines as blue shaded spans
    for line in lines:
        s = line.get("start"); e = line.get("end")
        if s is not None and e is not None:
            ax.axvspan(s, e, alpha=0.14, color="#3a7", linewidth=0)
    # Section boundaries
    for t in features.get("section_boundaries_s", []):
        ax.axvline(t, color="red", linestyle="--", alpha=0.6, linewidth=1.2)
    # Drum onsets as orange ticks at top
    for t in features.get("drum_onsets_s", []):
        ax.axvline(t, color="#f80", alpha=0.55, linewidth=0.9)
    ax.set_ylabel("spectral novelty\n(beats gray, drums orange,\nsections red --, lyrics green)")
    ax.grid(alpha=0.15, axis="x")

    # Panel 1: RMS envelope + sections
    ax = axes[1]
    if features.get("rms"):
        ax.plot(features["rms_times_s"], features["rms"], color="#2a8", linewidth=1.0)
    for t in features.get("section_boundaries_s", []):
        ax.axvline(t, color="red", linestyle="--", alpha=0.6, linewidth=1.2)
    ax.set_ylabel("RMS envelope\n(loud/soft, section boundaries red --)")
    ax.grid(alpha=0.15, axis="x")

    # Panel 2: drum strength
    ax = axes[2]
    if features.get("drum_strength"):
        ax.plot(features["drum_strength_times_s"], features["drum_strength"],
                color="#f80", linewidth=0.8)
    # Mark detected onsets
    for t in features.get("drum_onsets_s", []):
        ax.axvline(t, color="#a50", alpha=0.3, linewidth=0.6)
    ax.set_ylabel("drum onset strength\n(detected onsets dim orange)")
    ax.grid(alpha=0.15, axis="x")

    # Panel 3: lyric lines as labelled bars at their timing
    ax = axes[3]
    for i, line in enumerate(lines):
        s = line.get("start"); e = line.get("end")
        if s is None or e is None:
            continue
        ax.plot([s, e], [i, i], color="#3a7", linewidth=3)
        txt = line.get("text", "")[:70]
        ax.annotate(txt, (s, i), xytext=(4, 0), textcoords="offset points",
                    fontsize=7, va="center", color="#333")
    ax.set_ylabel("lyric lines")
    ax.set_yticks([])
    ax.set_xlabel("time (s)")
    ax.set_xlim(0, duration)
    ax.grid(alpha=0.15, axis="x")

    plt.tight_layout(rect=[0, 0, 1, 0.98])
    plt.savefig(out_path, dpi=90, bbox_inches="tight")
    plt.close(fig)


def build_index_html(run_dir: Path, song_summaries: list) -> None:
    rows = []
    for s in song_summaries:
        rows.append(
            f"<section><h2>{escape(s['song'])}</h2>"
            f"<div class='meta'>duration {s['duration_s']:.1f} s · "
            f"tempo {s['tempo_bpm']:.1f} BPM · "
            f"{s['n_beats']} beats · {s['n_drum_onsets']} drum onsets · "
            f"{s['n_sections']} section boundaries · {s['n_lines']} lyric lines</div>"
            f"<a href='{escape(s['png'])}'><img src='{escape(s['png'])}'></a>"
            f"<div class='meta'><a href='{escape(s['json'])}'>features.json</a></div>"
            f"</section>"
        )
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>POC 22 — Audio Timeline</title>
<style>
  body{{font-family:-apple-system,sans-serif;margin:1.5rem;max-width:1800px}}
  section{{margin-bottom:2rem;border-top:1px solid #0003;padding-top:1rem}}
  img{{width:100%;max-width:100%;display:block;border:1px solid #0003}}
  .meta{{font-size:12px;color:#666;margin:4px 0}}
  a{{color:#06f}}
</style></head><body>
<h1>POC 22 — Audio feature timelines</h1>
<p>For each track: beats (gray), drum onsets (orange ticks), section boundaries (red dashes), lyric lines (green). Click a figure to open full-size.</p>
{''.join(rows)}
</body></html>"""
    (run_dir / "index.html").write_text(html)


def main():
    run_dir = make_run_dir(__file__)
    print(f"Run dir: {run_dir}")

    songs = sorted(MUSIC_DIR.glob("*.wav"))
    if not songs:
        print("No .wav files in music/", file=sys.stderr)
        sys.exit(1)

    summaries = []
    for song_wav in songs:
        song_stem = song_wav.stem
        print(f"\n=== {song_stem} ===")
        drums_path = STEMS_CACHE / song_stem / "stems" / "htdemucs_6s" / song_stem / "drums.wav"
        if not drums_path.exists():
            print(f"  WARN: drums stem missing at {drums_path} — falling back to full-mix onsets only")
            drums_path = None

        t0 = time.time()
        features = audio_features.extract(song_wav, drums_path)
        print(f"  features extracted in {time.time()-t0:.1f}s")

        aligned = load_aligned(song_stem)
        lines: list = aligned.get("lines", [])
        # lines from force_align.py have text but not per-line start/end — derive from words + text match
        # Use a simpler approach: use the segments list if present
        seg_lines = []
        segments = aligned.get("segments", [])
        if segments:
            for seg in segments:
                if "start" in seg and "end" in seg and "text" in seg:
                    seg_lines.append({"text": seg["text"], "start": float(seg["start"]), "end": float(seg["end"])})
        # Fallback: reconstruct from words by grouping on "line_idx" or line_records
        if not seg_lines and aligned.get("words"):
            # POC 7's force_align writes both "words" and "lines". Reconstruct line timings
            # by matching the first N tokens of each line to consecutive words.
            import re
            words = aligned["words"]
            line_records = aligned.get("lines", [])
            cursor = 0
            for lr in line_records:
                tokens = re.findall(r"[\w']+", lr.get("text", ""))
                n = len(tokens)
                if n == 0 or cursor + n > len(words):
                    continue
                group = words[cursor:cursor + n]
                if all(g.get("start") is not None for g in group):
                    seg_lines.append({
                        "text": lr["text"],
                        "start": float(group[0]["start"]),
                        "end": float(group[-1]["end"]),
                    })
                cursor += n
        print(f"  resolved {len(seg_lines)} lyric lines")

        png_path = run_dir / f"{song_stem}_timeline.png"
        json_path = run_dir / f"{song_stem}_features.json"
        plot_timeline(song_stem, features, seg_lines, png_path)
        json_path.write_text(json.dumps(
            {"song": song_stem, "features": features, "lines": seg_lines},
            indent=2, default=str,
        ))
        print(f"  saved {png_path.name} + {json_path.name}")

        summaries.append({
            "song": song_stem,
            "duration_s": features["duration_s"],
            "tempo_bpm": features["tempo_bpm"],
            "n_beats": len(features.get("beats_s", [])),
            "n_drum_onsets": len(features.get("drum_onsets_s", [])),
            "n_sections": len(features.get("section_boundaries_s", [])),
            "n_lines": len(seg_lines),
            "png": png_path.name,
            "json": json_path.name,
        })

    build_index_html(run_dir, summaries)
    print(f"\nIndex: {run_dir / 'index.html'}")


if __name__ == "__main__":
    main()
