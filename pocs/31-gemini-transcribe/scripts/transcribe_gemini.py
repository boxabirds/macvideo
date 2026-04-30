#!/usr/bin/env python
"""POC 31 — Transcribe sung vocals with Gemini's native audio input.

Reads GEMINI_API_KEY from .env at repo root (same pattern as POCs 5/6).
Uploads the vocals stem via the Files API (>20 MB inline cap), asks
gemini-2.5-pro for a verbatim transcript, writes JSON in a shape
POC 30's compare.py understands.

Usage:
    transcribe_gemini.py <vocals_in> <json_out>
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


MODEL_ID = "gemini-2.5-pro"
PROMPT = (
    "Transcribe the lyrics of this song verbatim. Output only the words "
    "that are sung, in the order they are sung, separated by spaces or "
    "newlines as makes sense for line breaks. Do NOT include section "
    "markers like [Chorus] or [Verse]. Do NOT include timestamps. Do NOT "
    "include any commentary, preamble, or explanation. Output the lyrics "
    "and nothing else."
)


def load_env(env_path: Path) -> None:
    """Same lightweight .env loader as POCs 5/6 — no python-dotenv dep."""
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <vocals_in> <json_out>", file=sys.stderr)
        return 2

    vocals_in = Path(sys.argv[1])
    json_out = Path(sys.argv[2])

    if not vocals_in.exists():
        print(f"ERROR: vocals file missing: {vocals_in}", file=sys.stderr)
        return 1

    repo_root = Path(__file__).resolve().parents[3]
    load_env(repo_root / ".env")

    if "GEMINI_API_KEY" not in os.environ:
        print("ERROR: GEMINI_API_KEY not set. Put it in .env at repo root.",
              file=sys.stderr)
        return 1

    from google import genai  # noqa: PLC0415

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    print(f"Model: {MODEL_ID}")
    print(f"Audio: {vocals_in} ({vocals_in.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"Prompt: {PROMPT[:80]}...")
    print()

    print("Uploading audio via Files API...")
    t_upload = time.time()
    uploaded = client.files.upload(file=str(vocals_in))
    upload_s = time.time() - t_upload
    print(f"  uploaded as {uploaded.name} in {upload_s:.1f}s")

    print(f"Generating transcription...")
    t_transcribe = time.time()
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=[uploaded, PROMPT],
    )
    transcribe_s = time.time() - t_transcribe
    print(f"  transcribe wall time: {transcribe_s:.1f}s")

    transcript_text = (response.text or "").strip()
    word_count = len(transcript_text.split())
    print(f"  approx words returned: {word_count}")

    # Cleanup uploaded file (Files API has a 48h auto-expiry but be tidy)
    try:
        client.files.delete(name=uploaded.name)
        print(f"  deleted uploaded file {uploaded.name}")
    except Exception as e:  # noqa: BLE001
        print(f"  (non-fatal) failed to delete uploaded file: {e}")

    out_payload = {
        "method": "gemini_transcribe",
        "model": MODEL_ID,
        "upload_wall_s": round(upload_s, 2),
        "transcribe_wall_s": round(transcribe_s, 2),
        "approx_word_count": word_count,
        "prompt": PROMPT,
        # compare.py reads segments[].text for non-whisper_timestamped methods
        "segments": [{"text": transcript_text}],
        "usage_metadata": (
            response.usage_metadata.model_dump()
            if getattr(response, "usage_metadata", None)
            else None
        ),
    }
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(out_payload, indent=2, default=str))
    print(f"Wrote {json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
