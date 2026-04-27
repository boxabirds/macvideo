"""Fake WhisperX transcription script for Story 14 integration tests.

CLI: --audio <vocals.wav> --out <transcript.txt>

Env vars mirror fake_demucs.py:
  FAKE_WHISPERX_FAIL=1       → non-zero exit.
  FAKE_WHISPERX_DELAY_S=N    → sleep before writing.
  FAKE_WHISPERX_PARTIAL=1    → write partial output before sleeping.
  FAKE_WHISPERX_TEXT=<text>  → override the transcript text (default: a
                               three-line synthetic transcript).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

DEFAULT_TRANSCRIPT = (
    "this is a fake transcript\n"
    "produced by the fake whisperx script\n"
    "for integration tests only\n"
)


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

    if os.environ.get("FAKE_WHISPERX_PARTIAL") == "1":
        out.write_text("PARTIAL\n")
        print("[fake-whisperx] wrote partial transcript", flush=True)

    delay_s = float(os.environ.get("FAKE_WHISPERX_DELAY_S", "0") or "0")
    if delay_s > 0:
        end = time.time() + delay_s
        while time.time() < end:
            time.sleep(0.05)

    text = os.environ.get("FAKE_WHISPERX_TEXT") or DEFAULT_TRANSCRIPT
    out.write_text(text)
    print("[fake-whisperx] wrote transcript", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
