"""Fake Demucs vocals-separation script for Story 14 integration tests.

CLI: --audio <input.wav> --out <vocals.wav>

Behaviour is configured via env vars so tests can simulate failure or
in-flight cancellation without monkey-patching subprocess internals:

  FAKE_DEMUCS_FAIL=1     → exit non-zero with a diagnostic message.
  FAKE_DEMUCS_DELAY_S=N  → sleep N seconds before writing the output. Tests
                           use this to set cancel_event mid-phase and verify
                           SIGTERM cleans up.
  FAKE_DEMUCS_PARTIAL=1  → write a partial vocals.wav before sleeping so the
                           cancellation test can verify the partial file is
                           cleaned up by the orchestrator.

On success, writes a 32-byte minimal WAV header to --out so the next phase
can read it as a valid file.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

MIN_WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x80>\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--audio", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    if os.environ.get("FAKE_DEMUCS_FAIL") == "1":
        print("[fake-demucs] forced failure", file=sys.stderr, flush=True)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if os.environ.get("FAKE_DEMUCS_PARTIAL") == "1":
        out.write_bytes(b"PARTIAL")
        print("[fake-demucs] wrote partial vocals.wav", flush=True)

    delay_s = float(os.environ.get("FAKE_DEMUCS_DELAY_S", "0") or "0")
    if delay_s > 0:
        # Sleep in small slices so SIGTERM lands quickly.
        end = time.time() + delay_s
        while time.time() < end:
            time.sleep(0.05)

    out.write_bytes(MIN_WAV_BYTES)
    print("[fake-demucs] wrote vocals.wav", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
