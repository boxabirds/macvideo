"""Fake whisperx_align.py for transcribe-stage integration tests.

Mirrors the real script's CLI + stdout shape so the editor's
subprocess_runner sees realistic [align] progress events. Avoids the
heavy whisperx/torch import at test time.

Produces a synthetic aligned.json with linearly-distributed word timings
across the audio duration, derived from the lyric file. The shape matches
what make_shots.py expects (words[].word/start/end + duration_s).

Audio duration is read from the WAV header where possible; falls back to
30s if the audio isn't a parseable WAV.

A second invocation with the same --out path will detect an existing
cache file and exit immediately without re-running — matches the real
flow where the editor only invokes whisperx_align.py if the cache file
is missing.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import time
from pathlib import Path

DEFAULT_DURATION_S = 30.0
WAV_RIFF_TAG = b"RIFF"
WAV_FMT_OFFSET = 28
WAV_BYTE_RATE_OFFSET = 28


def _emit(pct: int, message: str) -> None:
    print(f"[align] {pct}% {message}", flush=True)


def _wav_duration_s(audio: Path) -> float:
    """Extract duration from WAV header. Returns DEFAULT_DURATION_S on failure."""
    try:
        import wave
        with wave.open(str(audio), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return DEFAULT_DURATION_S


def _tokenize(line: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", line.lower())


def _clean_lyrics(raw: str) -> list[str]:
    """Inline subset of make_shots.clean_lyrics_lines — keeps the fake script
    self-contained (no sys.path mutation) while matching the real cleaner."""
    out = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        stripped = re.sub(r"^[*_]+|[*_]+$", "", s).strip()
        if re.match(r"^\[[^\]]+\]$", stripped):
            continue
        out.append(stripped)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lyrics")
    ap.add_argument("--model", default="en")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    audio_path = Path(args.audio)
    out_path = Path(args.out)
    lyrics_path = Path(args.lyrics) if args.lyrics else None

    _emit(0, f"loading {audio_path.name}")
    duration = _wav_duration_s(audio_path)
    _emit(15, f"audio loaded ({duration:.1f}s)")

    lyric_lines: list[str] = []
    if lyrics_path is not None and lyrics_path.exists():
        lyric_lines = _clean_lyrics(lyrics_path.read_text())

    if not lyric_lines:
        print("no lyric text available", file=sys.stderr)
        return 1

    _emit(50, "running fake forced alignment")
    # Distribute words linearly across [0, duration). Word duration = total
    # duration / total word count, capped at 1s to keep things realistic.
    all_words = []
    line_records = []
    for line_idx, line in enumerate(lyric_lines):
        line_records.append({"line_idx": line_idx, "text": line})
        for tok in _tokenize(line):
            all_words.append((line_idx, tok))
    if not all_words:
        print("no recognisable words in lyrics", file=sys.stderr)
        return 1

    word_dur = min(1.0, duration / len(all_words))
    words = []
    for i, (_line_idx, tok) in enumerate(all_words):
        start = (i / len(all_words)) * duration
        words.append({
            "word": tok,
            "start": round(start, 3),
            "end": round(start + word_dur, 3),
            "score": 0.99,
        })

    payload = {
        "audio": str(audio_path),
        "ground_truth": str(lyrics_path) if lyrics_path else None,
        "duration_s": round(duration, 3),
        "method": "fake_whisperx_align",
        "words": words,
        "word_count": len(words),
        "lines": line_records,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))
    _emit(100, f"done ({len(words)} words)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
