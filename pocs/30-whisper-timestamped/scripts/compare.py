#!/usr/bin/env python
"""POC 30 — Compare two transcripts vs ground-truth lyrics.

Computes word error rate (WER) and prints a diff so we can characterise
the kinds of errors each recipe makes (homophones, dropped lines, etc.).

Usage:
    compare.py <ground_truth_txt> <transcript_a_json> <transcript_b_json> <out_md>

Both transcripts are read in their respective JSON shapes:
- whisper_timestamped: segments[].words[].text/word
- whisperx_noprompt: segments[].text  (no word-level)

For comparison we flatten both to a list of normalised tokens (lowercase,
strip punctuation, drop section markers like [Verse 1]) and compute WER
via difflib's SequenceMatcher ratio.
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path


SECTION_MARKER_RE = re.compile(r"^\**\[[^\]]*\]\**\s*$")
PUNCT_RE = re.compile(r"[^a-z0-9\s']")


def tokenise(text: str) -> list[str]:
    text = text.lower()
    text = PUNCT_RE.sub(" ", text)
    return [w for w in text.split() if w]


def load_ground_truth(path: Path) -> list[str]:
    """Same cleaning as make_shots.py / transcribe.py — strip comments,
    section markers, markdown emphasis."""
    out_words = []
    for raw_line in path.read_text().splitlines():
        s = raw_line.strip()
        if not s or s.startswith("#"):
            continue
        if SECTION_MARKER_RE.match(s):
            continue
        cleaned = s.strip("*").rstrip()
        if not cleaned:
            continue
        out_words.extend(tokenise(cleaned))
    return out_words


def load_transcript_words(path: Path) -> tuple[list[str], dict]:
    """Returns (word_list, metadata_dict). Handles both transcript shapes."""
    payload = json.loads(path.read_text())
    method = payload.get("method", "unknown")
    words: list[str] = []
    if method == "whisper_timestamped":
        for seg in payload.get("segments", []):
            for w in seg.get("words", []):
                # whisper-timestamped uses 'text' for the word string
                token = (w.get("text") or w.get("word") or "").strip()
                if token:
                    words.extend(tokenise(token))
    else:
        # whisperx_noprompt: per-segment text strings
        for seg in payload.get("segments", []):
            text = seg.get("text", "")
            words.extend(tokenise(text))
    return words, payload


def wer(reference: list[str], hypothesis: list[str]) -> tuple[float, int, int, int, int]:
    """Word error rate via Levenshtein-style edit distance.
    Returns (wer, substitutions, insertions, deletions, ref_len)."""
    n, m = len(reference), len(hypothesis)
    if n == 0:
        return (0.0 if m == 0 else 1.0, 0, m, 0, 0)
    # DP table
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if reference[i - 1] == hypothesis[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = 1 + min(d[i - 1][j],     # deletion
                                  d[i][j - 1],     # insertion
                                  d[i - 1][j - 1]) # substitution
    # Backtrack to count operation types
    i, j = n, m
    subs = ins = dels = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and reference[i - 1] == hypothesis[j - 1]:
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + 1:
            subs += 1
            i, j = i - 1, j - 1
        elif j > 0 and d[i][j] == d[i][j - 1] + 1:
            ins += 1
            j -= 1
        else:
            dels += 1
            i -= 1
    return (d[n][m] / n, subs, ins, dels, n)


def diff_sample(reference: list[str], hypothesis: list[str], window: int = 80) -> str:
    """Show first window words side by side using difflib."""
    sm = difflib.SequenceMatcher(None, reference[:window], hypothesis[:window])
    lines = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        ref_chunk = " ".join(reference[i1:i2]) or "—"
        hyp_chunk = " ".join(hypothesis[j1:j2]) or "—"
        if tag == "equal":
            continue  # skip matching runs
        lines.append(f"  [{tag:>7}] ref: {ref_chunk!r}")
        lines.append(f"            hyp: {hyp_chunk!r}")
    return "\n".join(lines) if lines else "  (no differences in first window)"


def main() -> int:
    if len(sys.argv) != 5:
        print(f"Usage: {sys.argv[0]} <ground_truth_txt> <transcript_m_json> "
              f"<transcript_w_json> <out_md>", file=sys.stderr)
        return 2

    gt_path = Path(sys.argv[1])
    m_path = Path(sys.argv[2])
    w_path = Path(sys.argv[3])
    out_md = Path(sys.argv[4])

    gt = load_ground_truth(gt_path)
    m_words, m_meta = load_transcript_words(m_path)
    w_words, w_meta = load_transcript_words(w_path)

    m_wer, m_subs, m_ins, m_dels, _ = wer(gt, m_words)
    w_wer, w_subs, w_ins, w_dels, _ = wer(gt, w_words)

    md = []
    md.append(f"# POC 30 comparison vs {gt_path.name}\n")
    md.append(f"Ground-truth words: **{len(gt)}**\n")
    md.append("## Variant M — whisper-timestamped\n")
    md.append(f"- Hypothesis words: {len(m_words)}")
    md.append(f"- WER: **{m_wer:.1%}**  (subs={m_subs}, ins={m_ins}, dels={m_dels})")
    md.append(f"- Wall time: {m_meta.get('transcribe_wall_s')}s")
    md.append(f"- Word accuracy ≈ **{(1 - m_wer):.1%}**\n")
    md.append("## Variant W — WhisperX (no initial_prompt)\n")
    md.append(f"- Hypothesis words: {len(w_words)}")
    md.append(f"- WER: **{w_wer:.1%}**  (subs={w_subs}, ins={w_ins}, dels={w_dels})")
    md.append(f"- Wall time: {w_meta.get('transcribe_wall_s')}s")
    md.append(f"- Word accuracy ≈ **{(1 - w_wer):.1%}**\n")
    md.append("## Sample diffs (first 80 reference words)\n")
    md.append("### Variant M\n```")
    md.append(diff_sample(gt, m_words))
    md.append("```\n")
    md.append("### Variant W\n```")
    md.append(diff_sample(gt, w_words))
    md.append("```\n")
    md.append("## Recommendation\n")
    if m_wer < w_wer:
        md.append(f"**Variant M wins** by {(w_wer - m_wer)*100:.1f} pp.")
    elif w_wer < m_wer:
        md.append(f"**Variant W wins** by {(m_wer - w_wer)*100:.1f} pp.")
    else:
        md.append("Tie — pick on other criteria (wall time, model size, dependency cost).")

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(md))
    print(f"Wrote {out_md}")
    print(f"Variant M WER: {m_wer:.1%}   Variant W WER: {w_wer:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
