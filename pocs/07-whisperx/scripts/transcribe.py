#!/usr/bin/env python
"""POC 7 — WhisperX transcription with forced alignment.

Reproducible. Configuration choices documented inline — no corner-cutting:
- compute_type="float32" (not int8) — int8 drops quiet/whispered sections
- device="cpu" — WhisperX does not support MPS in 2026 (missing Metal ops)
- VAD thresholds loosened (0.35/0.25) — default pyannote VAD too strict for singing
- initial_prompt seeded from the supplied lyrics.txt — biases the model toward
  the user's vocabulary, fixes phonetic mishearings
- language="en" — skip auto-detection

Usage:
    transcribe.py <audio_in> <json_out> [lyrics_txt]

The lyrics_txt arg is optional but strongly recommended — it becomes the
initial_prompt for the STT step.
"""

import json
import re
import sys
from pathlib import Path

import whisperx


# Match markdown section markers like **[Verse 1]** or *[Chorus]*
SECTION_MARKER_RE = re.compile(r"^\*+\[[^\]]*\]\*+\s*$")


def clean_lyrics_for_prompt(raw: str) -> str:
    """Strip markdown headers and section markers, return a plain-text prompt."""
    out_lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if SECTION_MARKER_RE.match(s):
            continue
        out_lines.append(s.strip("*").rstrip())
    return " ".join(out_lines)


def main():
    if len(sys.argv) < 3:
        print("Usage: transcribe.py <audio_in> <json_out> [lyrics_txt]", file=sys.stderr)
        sys.exit(2)

    audio_in = Path(sys.argv[1])
    json_out = Path(sys.argv[2])
    lyrics_path = Path(sys.argv[3]) if len(sys.argv) >= 4 else None

    initial_prompt = None
    if lyrics_path and lyrics_path.exists():
        initial_prompt = clean_lyrics_for_prompt(lyrics_path.read_text())
        print(f"initial_prompt: {len(initial_prompt.split())} words from {lyrics_path}")
    else:
        print("initial_prompt: (none — no lyrics file supplied)")

    device = "cpu"
    compute_type = "float32"
    model_name = "large-v3"
    vad_options = {"vad_onset": 0.35, "vad_offset": 0.25}

    asr_options = {}
    if initial_prompt:
        asr_options["initial_prompt"] = initial_prompt

    print(f"Loading WhisperX {model_name!r} on {device} ({compute_type})...")
    model = whisperx.load_model(
        model_name,
        device=device,
        compute_type=compute_type,
        vad_options=vad_options,
        asr_options=asr_options or None,
    )

    print(f"Loading audio: {audio_in}")
    audio = whisperx.load_audio(str(audio_in))

    print("Transcribing (coarse segments)...")
    result = model.transcribe(audio, batch_size=8, language="en")
    print(f"  {len(result['segments'])} coarse segments")

    print("Loading wav2vec2 alignment model (en)...")
    align_model, metadata = whisperx.load_align_model(
        language_code="en", device=device
    )

    print("Forced alignment for word-level timings...")
    aligned = whisperx.align(
        result["segments"],
        align_model,
        metadata,
        audio,
        device,
        return_char_alignments=False,
    )

    words = []
    for seg in aligned.get("segments", []):
        for w in seg.get("words", []):
            words.append({
                "word": w.get("word", "").strip(),
                "start": w.get("start"),
                "end": w.get("end"),
                "score": w.get("score"),
            })

    out = {
        "language": "en",
        "model": model_name,
        "compute_type": compute_type,
        "vad_options": vad_options,
        "initial_prompt_used": bool(initial_prompt),
        "segments": aligned.get("segments", []),
        "words": words,
        "word_count": len(words),
    }
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote {json_out} — {len(words)} words, {len(aligned.get('segments', []))} segments")


if __name__ == "__main__":
    main()
