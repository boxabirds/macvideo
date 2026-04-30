#!/usr/bin/env python
"""POC 30 — Variant W: WhisperX baseline with no initial_prompt.

POC 07's recipe but with the lyrics-derived initial_prompt removed,
since the whole point of story 14 is that no .txt exists yet.

Usage:
    transcribe_whisperx_noprompt.py <vocals_in> <json_out>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


MODEL_NAME = "large-v3"
COMPUTE_TYPE = "float32"
BATCH_SIZE = 8
VAD_OPTIONS = {"vad_onset": 0.35, "vad_offset": 0.25}


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <vocals_in> <json_out>", file=sys.stderr)
        return 2

    vocals_in = Path(sys.argv[1])
    json_out = Path(sys.argv[2])

    if not vocals_in.exists():
        print(f"ERROR: vocals file missing: {vocals_in}", file=sys.stderr)
        return 1

    print(f"Loading WhisperX {MODEL_NAME!r} on cpu ({COMPUTE_TYPE})...")
    t_load = time.time()
    import whisperx  # noqa: PLC0415
    model = whisperx.load_model(
        MODEL_NAME,
        device="cpu",
        compute_type=COMPUTE_TYPE,
        vad_options=VAD_OPTIONS,
    )
    print(f"  loaded in {time.time() - t_load:.1f}s")

    print(f"Loading audio: {vocals_in}")
    audio = whisperx.load_audio(str(vocals_in))

    print("Transcribing (no initial_prompt)...")
    t_transcribe = time.time()
    result = model.transcribe(audio, batch_size=BATCH_SIZE, language="en")
    transcribe_s = time.time() - t_transcribe
    print(f"  transcribe wall time: {transcribe_s:.1f}s")

    segments = result.get("segments", [])
    word_count = sum(len(seg.get("text", "").split()) for seg in segments)
    print(f"  segments: {len(segments)}, approx words: {word_count}")

    out_payload = {
        "method": "whisperx_noprompt",
        "model": MODEL_NAME,
        "device": "cpu",
        "compute_type": COMPUTE_TYPE,
        "vad_options": VAD_OPTIONS,
        "transcribe_wall_s": round(transcribe_s, 2),
        "segments": segments,
        "segment_count": len(segments),
        "approx_word_count": word_count,
    }
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(out_payload, indent=2, default=str))
    print(f"Wrote {json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
