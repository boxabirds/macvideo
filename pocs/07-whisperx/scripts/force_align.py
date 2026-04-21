#!/usr/bin/env python
"""Force-align ground-truth lyrics to audio via wav2vec2 CTC.

No STT. We already have the words (from music/<track>.txt). We only need
their timings. This script loads the WhisperX alignment model (a wav2vec2
CTC model) and aligns the supplied text to the audio directly.

Output: 100% word accuracy (words come from ground truth), acoustic timings
(from the wav2vec2 model, not interpolation).

Usage:
    force_align.py <audio_in> <lyrics_txt> <out_json>
"""

import json
import re
import sys
from pathlib import Path

import whisperx


SECTION_MARKER_RE = re.compile(r"^\*+\[[^\]]*\]\*+\s*$")


def parse_lyrics(raw: str):
    """Return cleaned plain-text lyrics and a list of line records."""
    line_records = []
    plain_lines = []
    line_idx = 0
    for raw_line in raw.splitlines():
        s = raw_line.strip()
        if not s or s.startswith("#"):
            continue
        if SECTION_MARKER_RE.match(s):
            continue
        cleaned = s.strip("*").rstrip()
        if not cleaned:
            continue
        plain_lines.append(cleaned)
        line_records.append({"line_idx": line_idx, "text": cleaned})
        line_idx += 1
    plain_text = " ".join(plain_lines)
    return plain_text, line_records


def main():
    if len(sys.argv) != 4:
        print("Usage: force_align.py <audio_in> <lyrics_txt> <out_json>", file=sys.stderr)
        sys.exit(2)

    audio_path = Path(sys.argv[1])
    lyrics_path = Path(sys.argv[2])
    out_path = Path(sys.argv[3])

    device = "cpu"

    print(f"Loading audio: {audio_path}")
    audio = whisperx.load_audio(str(audio_path))
    sample_rate = 16000  # whisperx.load_audio resamples to 16 kHz
    duration = len(audio) / sample_rate
    print(f"  duration: {duration:.2f} s")

    plain_text, line_records = parse_lyrics(lyrics_path.read_text())
    print(f"Ground-truth lyrics: {len(plain_text.split())} words, {len(line_records)} lines")

    # Single segment spanning the whole audio. wav2vec2 forced alignment
    # distributes the words according to actual acoustic evidence, not
    # linear interpolation.
    segments = [{"text": plain_text, "start": 0.0, "end": duration}]

    print(f"Loading wav2vec2 alignment model (en) on {device}...")
    align_model, metadata = whisperx.load_align_model(
        language_code="en", device=device
    )

    print("Forced alignment...")
    result = whisperx.align(
        segments, align_model, metadata, audio, device,
        return_char_alignments=False,
    )

    # Flatten words
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            words.append({
                "word": w.get("word", "").strip(),
                "start": w.get("start"),
                "end": w.get("end"),
                "score": w.get("score"),
            })

    out = {
        "audio": str(audio_path),
        "ground_truth": str(lyrics_path),
        "duration_s": round(duration, 3),
        "method": "wav2vec2_forced_align",
        "words": words,
        "word_count": len(words),
        "lines": line_records,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote {out_path} — {len(words)} words")


if __name__ == "__main__":
    main()
