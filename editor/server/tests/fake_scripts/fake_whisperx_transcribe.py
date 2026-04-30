"""Fake WhisperX transcription script for Story 18 integration tests.

CLI: --audio <vocals.wav> --out <json_out>

Outputs timestamped JSON segments (Story 18: direct to DB).

Env vars mirror fake_demucs.py:
  FAKE_WHISPERX_FAIL=1       → non-zero exit.
  FAKE_WHISPERX_DELAY_S=N    → sleep before writing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

DEFAULT_SEGMENTS = [
    {"text": "this is a fake segment", "start": 0.0, "end": 2.1},
    {"text": "produced by the fake whisperx script", "start": 2.1, "end": 5.3},
    {"text": "for integration tests only", "start": 5.3, "end": 8.5},
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--audio", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    if os.environ.get("FAKE_WHISPERX_FAIL") == "1":
        print("[fake-whisperx] forced failure", file=sys.stderr, flush=True)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    delay_s = float(os.environ.get("FAKE_WHISPERX_DELAY_S", "0") or "0")
    if delay_s > 0:
        end = time.time() + delay_s
        while time.time() < end:
            time.sleep(0.05)

    segments = DEFAULT_SEGMENTS
    payload = {
        "method": "fake_whisperx",
        "segments": segments,
        "segment_count": len(segments),
    }
    out.write_text(json.dumps(payload, indent=2))
    print("[fake-whisperx] wrote json with segments", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
