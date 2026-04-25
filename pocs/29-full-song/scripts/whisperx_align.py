#!/usr/bin/env python
"""Force-align lyrics to audio with WhisperX, producing aligned.json.

Used by the editor's transcribe stage to populate the WhisperX cache for a
song that doesn't have one yet. Output JSON shape matches the existing files
under pocs/29-full-song/whisperx_cache/, so make_shots.py consumes it
unchanged.

Usage:
    whisperx_align.py --audio <path.wav> --out <path.aligned.json>
                      [--lyrics <path.txt>]
                      [--model en] [--device cpu|mps|cuda]

Progress events are emitted on stdout in the form `[align] <pct>% <message>`
so the editor's subprocess_runner can surface them as an ETA.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path


SECTION_MARKER_RE = re.compile(r"^\*+\[[^\]]*\]\*+\s*$")
WAV2VEC_SAMPLE_RATE = 16000


def _emit(pct: int, message: str) -> None:
    """Write a progress line and flush so the parent process sees it live."""
    print(f"[align] {pct}% {message}", flush=True)


def _parse_lyrics(raw: str) -> tuple[str, list[dict]]:
    """Return (plain_text_for_alignment, line_records_for_metadata)."""
    line_records: list[dict] = []
    plain_lines: list[str] = []
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
    return " ".join(plain_lines), line_records


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--audio", required=True, help="path to source .wav/.mp3")
    ap.add_argument("--out", required=True, help="path to write aligned.json")
    ap.add_argument("--lyrics", help="path to lyrics .txt (recommended for forced alignment)")
    ap.add_argument("--model", default="en", help="wav2vec2 alignment language code")
    ap.add_argument("--device", default="cpu", choices=["cpu", "mps", "cuda"])
    args = ap.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"audio file not found: {audio_path}", file=sys.stderr)
        return 1

    out_path = Path(args.out)
    lyrics_path = Path(args.lyrics) if args.lyrics else None
    if lyrics_path is not None and not lyrics_path.exists():
        print(f"lyrics file not found: {lyrics_path}", file=sys.stderr)
        return 1

    t_start = time.time()
    _emit(0, f"loading audio {audio_path.name}")

    try:
        import whisperx  # noqa: PLC0415  (heavy import deferred until needed)
    except Exception as exc:  # noqa: BLE001
        print(f"failed to import whisperx: {exc}", file=sys.stderr)
        return 1

    try:
        audio = whisperx.load_audio(str(audio_path))
    except Exception as exc:  # noqa: BLE001
        print(f"failed to load audio: {exc}", file=sys.stderr)
        return 1
    duration = len(audio) / WAV2VEC_SAMPLE_RATE
    _emit(15, f"audio loaded ({duration:.1f}s)")

    if lyrics_path is not None:
        plain_text, line_records = _parse_lyrics(lyrics_path.read_text())
    else:
        plain_text, line_records = "", []

    if not plain_text:
        # Without lyrics we cannot do forced alignment at all — the wav2vec2
        # path needs ground-truth text. Fail loudly so the caller knows the
        # editor's preflight should have caught this.
        print(
            "no lyric text available — forced alignment requires --lyrics with "
            "at least one recognisable line",
            file=sys.stderr,
        )
        return 1

    _emit(25, "loading wav2vec2 model")
    try:
        align_model, metadata = whisperx.load_align_model(
            language_code=args.model, device=args.device,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"failed to load alignment model: {exc}", file=sys.stderr)
        return 1

    _emit(50, "running forced alignment")
    segments = [{"text": plain_text, "start": 0.0, "end": duration}]
    try:
        result = whisperx.align(
            segments, align_model, metadata, audio, args.device,
            return_char_alignments=False,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"alignment failed: {exc}", file=sys.stderr)
        return 1

    words: list[dict] = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            words.append({
                "word": (w.get("word") or "").strip(),
                "start": w.get("start"),
                "end": w.get("end"),
                "score": w.get("score"),
            })

    payload = {
        "audio": str(audio_path),
        "ground_truth": str(lyrics_path) if lyrics_path else None,
        "duration_s": round(duration, 3),
        "method": "wav2vec2_forced_align",
        "words": words,
        "word_count": len(words),
        "lines": line_records,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    elapsed = time.time() - t_start
    _emit(100, f"done ({len(words)} words, {elapsed:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
