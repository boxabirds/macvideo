#!/usr/bin/env python
"""Post-process WhisperX output against ground-truth lyrics.

Takes a WhisperX transcript and a lyrics.txt file. Uses sequence alignment
to match Whisper's (potentially imperfect) word stream against the correct
ground-truth word stream. Substitutes the ground-truth word wherever
Whisper got it wrong, keeping Whisper's timing.

Result: 100% word accuracy, Whisper timings preserved on matched and
substituted words, interpolated timings on words Whisper missed entirely.

Usage:
    ground_truth_match.py <transcript_json> <lyrics_txt> <out_json>
"""

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path


SECTION_MARKER_RE = re.compile(r"^\*+\[[^\]]*\]\*+\s*$")
WORD_RE = re.compile(r"[\w']+(?:-[\w']+)*")


def parse_lyrics(raw: str):
    """Parse lyrics markdown.

    Returns a list of line records: [{"line_idx", "text", "words"}, ...]
    and a flat list of (word, line_idx) for matching.
    """
    line_records = []
    flat = []
    line_idx = 0
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if SECTION_MARKER_RE.match(s):
            continue
        cleaned = s.strip("*").rstrip()
        words = WORD_RE.findall(cleaned)
        if not words:
            continue
        line_records.append({"line_idx": line_idx, "text": cleaned, "words": words})
        for w in words:
            flat.append((w, line_idx))
        line_idx += 1
    return line_records, flat


def norm(w: str) -> str:
    return re.sub(r"[^\w]", "", w.lower())


def interpolate(prev_end: float, next_start: float, n: int):
    """Split the gap between two anchors into n evenly-spaced timings."""
    span = next_start - prev_end
    # Guard against negative / zero spans when anchors are coincident
    if span <= 0:
        span = n * 0.3
    return [prev_end + span * (k + 1) / (n + 1) for k in range(n)]


def _prev_end(whisper_words, i):
    return whisper_words[i - 1]["end"] if i > 0 else 0.0


def _next_start(whisper_words, i, fallback):
    return whisper_words[i]["start"] if i < len(whisper_words) else fallback


def align_to_ground_truth(whisper_words, gt_flat):
    """Align Whisper's word stream to the ground-truth word stream."""
    gt_words = [x[0] for x in gt_flat]
    gt_lines = [x[1] for x in gt_flat]
    w_norm = [norm(w["word"]) for w in whisper_words]
    g_norm = [norm(g) for g in gt_words]

    matcher = SequenceMatcher(None, w_norm, g_norm, autojunk=False)
    out = []

    def emit(gt_i, start, end, source, **extras):
        entry = {
            "word": gt_words[gt_i],
            "line_idx": gt_lines[gt_i],
            "start": round(float(start), 3),
            "end": round(float(end), 3),
            "source": source,
        }
        entry.update(extras)
        out.append(entry)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                w = whisper_words[i1 + k]
                emit(j1 + k, w["start"], w["end"], "match")

        elif tag == "replace":
            nw, ng = i2 - i1, j2 - j1
            n = min(nw, ng)
            for k in range(n):
                w = whisper_words[i1 + k]
                emit(
                    j1 + k, w["start"], w["end"], "substitute",
                    whisper_heard=w["word"],
                )
            if ng > nw:
                prev = whisper_words[i1 + nw - 1]["end"] if nw > 0 else _prev_end(whisper_words, i1)
                nxt = _next_start(whisper_words, i2, prev + 0.3 * (ng - nw))
                times = interpolate(prev, nxt, ng - nw)
                for k in range(nw, ng):
                    t = times[k - nw]
                    emit(j1 + k, t, t + 0.2, "interpolated")

        elif tag == "delete":
            # Whisper heard words not in ground truth. Drop — probably ad-lib
            # or mis-segmentation. The user can re-enable if ad-libs matter.
            pass

        elif tag == "insert":
            ng = j2 - j1
            prev = _prev_end(whisper_words, i1)
            nxt = _next_start(whisper_words, i1, prev + 0.3 * ng)
            times = interpolate(prev, nxt, ng)
            for k in range(ng):
                emit(j1 + k, times[k], times[k] + 0.2, "interpolated")

    return out


def build_segments(aligned_words, line_records):
    """Group aligned words by line to produce line-level segments with timings."""
    segments = []
    for rec in line_records:
        line_words = [w for w in aligned_words if w["line_idx"] == rec["line_idx"]]
        if not line_words:
            continue
        segments.append({
            "line_idx": rec["line_idx"],
            "text": rec["text"],
            "start": line_words[0]["start"],
            "end": line_words[-1]["end"],
            "words": line_words,
        })
    return segments


def main():
    if len(sys.argv) != 4:
        print(
            "Usage: ground_truth_match.py <transcript_json> <lyrics_txt> <out_json>",
            file=sys.stderr,
        )
        sys.exit(2)

    transcript_path = Path(sys.argv[1])
    lyrics_path = Path(sys.argv[2])
    out_path = Path(sys.argv[3])

    transcript = json.loads(transcript_path.read_text())
    line_records, gt_flat = parse_lyrics(lyrics_path.read_text())
    whisper_words = transcript.get("words", [])

    aligned_words = align_to_ground_truth(whisper_words, gt_flat)
    segments = build_segments(aligned_words, line_records)

    stats = {
        "ground_truth_words": len(gt_flat),
        "whisper_words": len(whisper_words),
        "output_words": len(aligned_words),
        "matched": sum(1 for w in aligned_words if w["source"] == "match"),
        "substituted": sum(1 for w in aligned_words if w["source"] == "substitute"),
        "interpolated": sum(1 for w in aligned_words if w["source"] == "interpolated"),
    }
    denom = max(stats["output_words"], 1)
    stats["match_rate"] = round(stats["matched"] / denom, 3)
    stats["substitute_rate"] = round(stats["substituted"] / denom, 3)
    stats["interpolated_rate"] = round(stats["interpolated"] / denom, 3)
    stats["word_recovery"] = round(
        stats["output_words"] / max(stats["ground_truth_words"], 1), 3
    )

    out = {
        "source_transcript": str(transcript_path),
        "ground_truth": str(lyrics_path),
        "words": aligned_words,
        "segments": segments,
        "stats": stats,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))

    print(f"Wrote {out_path}")
    print(f"  ground-truth words : {stats['ground_truth_words']}")
    print(f"  whisper words      : {stats['whisper_words']}")
    print(f"  output words       : {stats['output_words']} "
          f"(recovery {stats['word_recovery']:.1%})")
    print(f"  matched            : {stats['matched']} ({stats['match_rate']:.1%})")
    print(f"  substituted        : {stats['substituted']} ({stats['substitute_rate']:.1%})")
    print(f"  interpolated       : {stats['interpolated']} ({stats['interpolated_rate']:.1%})")


if __name__ == "__main__":
    main()
