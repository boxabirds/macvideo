"""Build a shot list for a song from WhisperX aligned.json + song lyrics.

A "shot" is one tuple of:
  - target_text  : the lyric line (or "[instrumental]" / "[intro]" filler)
  - start_s, end_s, duration_s
  - num_frames   : rounded to LTX's 1 + 8k rule
  - kind         : "lyric" | "intro" | "outro" | "gap"

Rules:
  - One shot per lyric line (line groups = paragraphs in the .txt file)
  - Intro gap (0 → first-word) becomes one or more shots
  - Any gap between lyric lines > MIN_GAP_FOR_AMBIENT becomes an ambient shot
  - All shots clamped to [MIN_SHOT_S, MAX_SHOT_S]
  - Long shots split at MAX_SHOT_S boundaries (rare, but safe)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FPS = 30
MIN_SHOT_S = 0.3           # LTX minimum: num_frames >= 9 (1+8*1) = 0.3s at 30fps
# No MAX_SHOT_S cap — scene duration dictates. LTX memory is flat w.r.t. frames.
MAX_SHOT_S = float("inf")
MIN_GAP_FOR_AMBIENT = 3.0  # gap longer than this becomes its own ambient shot
LINE_TAIL_CUSHION_S = 0.2  # extend shot after last word by this much


def round_to_frame_constraint(n_frames: int) -> int:
    """Round DOWN to the nearest 1+8k (the legacy behaviour)."""
    if n_frames < 9:
        return 9
    return ((n_frames - 1) // 8) * 8 + 1


def round_up_to_frame_constraint(n_frames: int) -> int:
    """Round UP to the nearest 1+8k. Used for contiguous-policy num_frames so
    rendered clips are always ≥ their audio-target span; concat-time trim
    then produces bit-perfect sync."""
    if n_frames <= 9:
        return 9
    return ((n_frames - 1 + 7) // 8) * 8 + 1


def clean_lyrics_lines(raw: str) -> list[str]:
    """Return list of non-empty, non-section-marker lyric lines in file order."""
    out = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        # Strip markdown emphasis wrappers (**, *, _) before checking for section markers
        stripped = re.sub(r"^[*_]+|[*_]+$", "", s).strip()
        if re.match(r"^\[[^\]]+\]$", stripped):
            continue
        out.append(stripped)
    return out


def group_words_into_lines(words: list[dict], lyric_lines: list[str]) -> list[dict]:
    """Greedy match words[] against lyric_lines[] and produce line spans.

    Words in aligned.json are in song order but don't carry line_idx. We walk
    the lyric_lines in order and consume enough words to cover each line.
    """
    def tokens(s: str) -> list[str]:
        return re.findall(r"[A-Za-z']+", s.lower())

    i = 0
    spans = []
    for line_idx, line in enumerate(lyric_lines):
        target_toks = tokens(line)
        if not target_toks:
            continue
        # Consume words from i until we've matched len(target_toks) tokens
        start_i = i
        consumed = 0
        while i < len(words) and consumed < len(target_toks):
            w_tok = tokens(words[i]["word"])
            if w_tok:
                consumed += len(w_tok)
            i += 1
        if consumed == 0:
            continue
        line_words = [w for w in words[start_i:i] if w.get("start") is not None]
        if not line_words:
            continue
        spans.append({
            "line_idx": line_idx,
            "text": line,
            "start_s": float(line_words[0]["start"]),
            "end_s": float(line_words[-1].get("end", line_words[-1]["start"] + 0.3)),
        })
    return spans


def build_shots(
    line_spans: list[dict],
    duration_s: float,
) -> list[dict]:
    """Produce contiguous shot list covering [0, duration_s]."""
    shots: list[dict] = []

    def add_shot(start: float, end: float, kind: str, text: str) -> None:
        dur = end - start
        if dur < MIN_SHOT_S:
            return  # skip tiny gaps; they'll merge with neighbouring shots
        # Divide evenly into N pieces each ≤ MAX_SHOT_S and ≥ MIN_SHOT_S
        num_pieces = max(1, int(dur / MAX_SHOT_S + 0.999))
        piece_dur = dur / num_pieces
        if piece_dur < MIN_SHOT_S and num_pieces > 1:
            num_pieces -= 1
            piece_dur = dur / max(num_pieces, 1)
        cursor = start
        for piece_idx in range(num_pieces):
            piece_target_end = start + (piece_idx + 1) * piece_dur
            raw_frames = round((piece_target_end - cursor) * FPS)
            nf = round_to_frame_constraint(raw_frames)
            actual_end = cursor + nf / FPS
            if actual_end > end + 0.2:
                # Shrink last piece to fit
                raw_frames = round((end - cursor) * FPS)
                nf = round_to_frame_constraint(raw_frames)
                actual_end = cursor + nf / FPS
            piece_text = text if piece_idx == 0 else f"{text} [cont.]"
            shots.append({
                "index": len(shots) + 1,
                "kind": kind,
                "target_text": piece_text,
                "start_s": round(cursor, 3),
                "end_s": round(actual_end, 3),
                "duration_s": round(nf / FPS, 3),
                "num_frames": nf,
                "lyric_line_idx": -1,
            })
            cursor = actual_end

    # Intro gap
    if line_spans:
        first_start = line_spans[0]["start_s"]
        if first_start > MIN_SHOT_S:
            add_shot(0.0, first_start - 0.1, "intro", "[instrumental intro]")

    # Lyric lines + gaps between them
    for i, sp in enumerate(line_spans):
        line_start = sp["start_s"]
        line_end = sp["end_s"] + LINE_TAIL_CUSHION_S
        # Gap before this line (if not the first)
        if i > 0:
            prev_end = line_spans[i - 1]["end_s"] + LINE_TAIL_CUSHION_S
            gap = line_start - prev_end
            if gap >= MIN_GAP_FOR_AMBIENT:
                add_shot(prev_end, line_start - 0.05, "gap", "[instrumental bridge]")
        shot_end = line_end
        # Stretch short lines a bit if next gap is generous
        if i + 1 < len(line_spans):
            next_start = line_spans[i + 1]["start_s"]
            if next_start - shot_end < MIN_GAP_FOR_AMBIENT:
                shot_end = max(shot_end, next_start - 0.05)
        raw_frames = round((shot_end - line_start) * FPS)
        nf = round_to_frame_constraint(max(raw_frames, round(MIN_SHOT_S * FPS)))
        actual_end = line_start + nf / FPS
        if actual_end - line_start > MAX_SHOT_S + 0.5:
            # Split into smaller pieces via add_shot logic
            add_shot(line_start, actual_end, "lyric", sp["text"])
            shots[-1]["lyric_line_idx"] = sp["line_idx"]
            continue
        shots.append({
            "index": len(shots) + 1,
            "kind": "lyric",
            "target_text": sp["text"],
            "start_s": round(line_start, 3),
            "end_s": round(actual_end, 3),
            "duration_s": round(nf / FPS, 3),
            "num_frames": nf,
            "lyric_line_idx": sp["line_idx"],
        })

    # Outro
    if line_spans:
        last_end = line_spans[-1]["end_s"] + LINE_TAIL_CUSHION_S
        if duration_s - last_end > MIN_SHOT_S:
            add_shot(last_end, duration_s, "outro", "[instrumental outro]")

    # Reindex
    for i, s in enumerate(shots, 1):
        s["index"] = i

    # Contiguous-coverage post-pass.
    # Every shot's end_s is set to the next shot's start_s exactly (last shot
    # runs to song end). num_frames is recomputed from the new duration and
    # rounded UP to 1+8k so the rendered clip is always ≥ its audio target;
    # the concat step trims to exact target for bit-perfect sync.
    for i in range(len(shots)):
        target_end = shots[i + 1]["start_s"] if i + 1 < len(shots) else duration_s
        start_s = shots[i]["start_s"]
        # Target duration = gap to next shot's start (no MIN_SHOT_S floor —
        # we want strict contiguous coverage; any tiny-shot rendering minimum
        # is handled by num_frames clamping to 9 below, and concat trims the
        # rendered clip to exactly `target_duration_s`).
        tgt_dur = max(target_end - start_s, 0.05)   # guard against zero / negative only
        nf = round_up_to_frame_constraint(int(round(tgt_dur * FPS)))
        shots[i]["end_s"] = round(start_s + tgt_dur, 3)
        shots[i]["target_duration_s"] = round(tgt_dur, 3)
        shots[i]["duration_s"] = round(nf / FPS, 3)  # rendered clip duration
        shots[i]["num_frames"] = nf

    return shots


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", required=True, choices=["busy-invisible", "chronophobia", "my-little-blackbird"])
    ap.add_argument("--whisperx", required=True, help="aligned.json path")
    ap.add_argument("--lyrics", required=True, help="lyrics .txt path")
    ap.add_argument("--out", required=True, help="shots.json output path")
    args = ap.parse_args()

    wx = json.loads(Path(args.whisperx).read_text())
    duration_s = float(wx.get("duration_s", 0))
    # Filter out section-marker tokens that leaked into forced alignment
    # when the source .txt didn't use **[Section]** wrappers.
    words = [
        w for w in wx.get("words", [])
        if "[" not in w.get("word", "") and "]" not in w.get("word", "")
    ]
    if duration_s <= 0:
        sys.exit("missing duration_s in whisperx json")

    lyric_lines = clean_lyrics_lines(Path(args.lyrics).read_text())
    line_spans = group_words_into_lines(words, lyric_lines)
    shots = build_shots(line_spans, duration_s)

    out = {
        "song": args.song,
        "duration_s": duration_s,
        "fps": FPS,
        "min_shot_s": MIN_SHOT_S,
        "max_shot_s": MAX_SHOT_S,
        "shot_count": len(shots),
        "total_covered_s": round(sum(s.get("target_duration_s", s["duration_s"]) for s in shots), 3),
        "shots": shots,
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"{args.song}: {len(shots)} shots, covers {out['total_covered_s']:.1f}s of {duration_s:.1f}s")
    for s in shots[:8]:
        print(f"  {s['index']:3d} [{s['start_s']:6.2f}-{s['end_s']:6.2f}] {s['kind']:6s} {s['target_text']!r}")
    if len(shots) > 8:
        print(f"  ... ({len(shots) - 8} more)")


if __name__ == "__main__":
    main()
