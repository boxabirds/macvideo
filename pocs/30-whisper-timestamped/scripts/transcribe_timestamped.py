#!/usr/bin/env python
"""POC 30 — Variant M: music2vid's whisper-timestamped recipe.

Mirrors music2vid/poc.py:
- model: whisper-timestamped 'medium'
- device: cpu (music2vid hard-codes cpu even with RTX 4090)
- vad: True
- beam_size=5, best_of=5
- temperature ladder: (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)

Usage:
    transcribe_timestamped.py <vocals_in> <json_out>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


MODEL_SIZE = "medium"
TEMPERATURE_LADDER = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
BEAM_SIZE = 5
BEST_OF = 5


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <vocals_in> <json_out>", file=sys.stderr)
        return 2

    vocals_in = Path(sys.argv[1])
    json_out = Path(sys.argv[2])

    if not vocals_in.exists():
        print(f"ERROR: vocals file missing: {vocals_in}", file=sys.stderr)
        return 1

    print(f"Loading whisper-timestamped {MODEL_SIZE!r} on cpu...")
    t_load = time.time()
    import whisper_timestamped as whisper  # noqa: PLC0415  (heavy import deferred)
    model = whisper.load_model(MODEL_SIZE, device="cpu")
    print(f"  loaded in {time.time() - t_load:.1f}s")

    print(f"Loading audio: {vocals_in}")
    audio = whisper.load_audio(str(vocals_in))

    print("Transcribing with VAD + temperature ladder...")
    t_transcribe = time.time()
    result = whisper.transcribe_timestamped(
        model, audio,
        language="en",
        vad=True,
        beam_size=BEAM_SIZE,
        best_of=BEST_OF,
        temperature=TEMPERATURE_LADDER,
    )
    transcribe_s = time.time() - t_transcribe
    print(f"  transcribe wall time: {transcribe_s:.1f}s")

    word_count = sum(len(seg.get("words", [])) for seg in result.get("segments", []))
    segment_count = len(result.get("segments", []))
    print(f"  segments: {segment_count}, words: {word_count}")

    out_payload = {
        "method": "whisper_timestamped",
        "model": MODEL_SIZE,
        "device": "cpu",
        "vad": True,
        "beam_size": BEAM_SIZE,
        "best_of": BEST_OF,
        "temperature": list(TEMPERATURE_LADDER),
        "transcribe_wall_s": round(transcribe_s, 2),
        "segments": result.get("segments", []),
        "word_count": word_count,
        "segment_count": segment_count,
    }
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(out_payload, indent=2, default=str))
    print(f"Wrote {json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
