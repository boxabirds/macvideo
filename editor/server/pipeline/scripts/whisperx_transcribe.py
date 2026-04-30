#!/usr/bin/env python
"""Transcribe a vocals stem for the editor audio-transcribe pipeline.

The editor calls this product-owned wrapper with:

    whisperx_transcribe.py --audio outputs/song/vocals.wav --out outputs/song/segments.json

It owns the stable CLI contract used by the application. Research and POC
scripts may change independently without breaking product runtime behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "large-v3"
DEFAULT_DEVICE = "cpu"
DEFAULT_COMPUTE_TYPE = "float32"
DEFAULT_BATCH_SIZE = 8
DEFAULT_LANGUAGE = "en"
DEFAULT_VAD_OPTIONS = {"vad_onset": 0.35, "vad_offset": 0.25}


def transcribe_vocals(
    audio: Path,
    out: Path,
    *,
    model_name: str = DEFAULT_MODEL,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_COMPUTE_TYPE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    language: str = DEFAULT_LANGUAGE,
    vad_options: dict[str, float] | None = None,
) -> dict[str, Any]:
    if not audio.exists():
        raise FileNotFoundError(f"audio not found at {audio}")

    vad = vad_options or DEFAULT_VAD_OPTIONS
    print(
        f"[whisperx-transcribe] loading {model_name!r} on {device} ({compute_type})",
        flush=True,
    )
    t_load = time.time()
    import whisperx  # noqa: PLC0415

    model = whisperx.load_model(
        model_name,
        device=device,
        compute_type=compute_type,
        vad_options=vad,
    )
    print(f"[whisperx-transcribe] loaded in {time.time() - t_load:.1f}s", flush=True)

    print(f"[whisperx-transcribe] loading audio: {audio}", flush=True)
    audio_data = whisperx.load_audio(str(audio))

    print("[whisperx-transcribe] transcribing", flush=True)
    t_transcribe = time.time()
    result = model.transcribe(audio_data, batch_size=batch_size, language=language)
    transcribe_s = time.time() - t_transcribe

    segments = result.get("segments", [])
    word_count = sum(len(seg.get("text", "").split()) for seg in segments)
    payload = {
        "method": "whisperx_transcribe",
        "model": model_name,
        "device": device,
        "compute_type": compute_type,
        "vad_options": vad,
        "language": language,
        "transcribe_wall_s": round(transcribe_s, 2),
        "segments": segments,
        "segment_count": len(segments),
        "approx_word_count": word_count,
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str))
    print(
        f"[whisperx-transcribe] wrote {out} "
        f"({len(segments)} segments, ~{word_count} words)",
        flush=True,
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--compute-type", default=DEFAULT_COMPUTE_TYPE)
    parser.add_argument("--batch-size", default=DEFAULT_BATCH_SIZE, type=int)
    parser.add_argument("--language", default=DEFAULT_LANGUAGE)
    args = parser.parse_args(argv)

    try:
        transcribe_vocals(
            args.audio,
            args.out,
            model_name=args.model,
            device=args.device,
            compute_type=args.compute_type,
            batch_size=args.batch_size,
            language=args.language,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[whisperx-transcribe] {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
