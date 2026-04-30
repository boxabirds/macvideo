# POC 30 — whisper-timestamped (revisit music2vid recipe)

**Goal:** Validate whether the transcription approach from `~/expts/music2vid` (whisper-timestamped + temperature ladder + medium model) still works in 2026 on Mac, and whether it produces a better audio-only transcript than POC 07's WhisperX + force-align stack does *without* a ground-truth lyrics file.

## Why

Story 14 (skip writing lyrics by hand) needs a transcription path for songs whose `.wav` arrives without a `.txt`. POC 07 only proved 100% accuracy *with* a ground-truth `.txt` (forced alignment makes that trivial). Without ground truth, the proven number is a single ~90% spot-check from POC 07 attempt 2. music2vid's recipe — whisper-timestamped, temperature ladder fallback, medium model — claimed real-world success on songs three years ago. Need to know if it still installs, runs on Mac, and produces a transcript at least as accurate as WhisperX-without-prompt before committing story 14 to one approach.

## Pass criteria

- [ ] `whisper-timestamped` installs cleanly under `uv` on macOS Apple Silicon, Python 3.11+
- [ ] Runs to completion on the existing `my-little-blackbird` vocals stem (no GPU)
- [ ] Produces a JSON transcript with word-level timestamps
- [ ] Word accuracy on `my-little-blackbird` ≥ 85% on a normalised diff against ground truth (`music/my-little-blackbird.txt`)
- [ ] Side-by-side comparison vs WhisperX large-v3 (no initial_prompt) on the same vocals stem documents which recipe wins, by how much, and on which kinds of error

## Inputs

- Audio: `pocs/07-whisperx/stems/htdemucs_6s/my-little-blackbird/vocals.wav` (already separated)
- Ground truth: `music/my-little-blackbird.txt`

Holding the vocal-separation step constant (htdemucs_6s) isolates the transcription stack as the variable. A follow-up could swap to mdx_extra (music2vid's choice) if results are inconclusive.

## Recipes under test

### Variant M — music2vid recipe

```python
import whisper_timestamped as whisper
model = whisper.load_model("medium", device="cpu")
result = whisper.transcribe_timestamped(
    model, audio,
    language="en",
    vad=True,
    beam_size=5, best_of=5,
    temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
)
```

### Variant W — WhisperX baseline (audio-only, no ground-truth prompt)

POC 07's existing config but without the `initial_prompt` step (since the whole point is no `.txt` is available).

```python
import whisperx
model = whisperx.load_model(
    "large-v3",
    device="cpu", compute_type="float32",
    vad_options={"vad_onset": 0.35, "vad_offset": 0.25},
)
result = model.transcribe(audio, batch_size=8, language="en")
```

## Comparison method

Both transcripts → flatten to a list of lowercased word tokens (strip punctuation, drop section markers like `[Verse 1]`). Same for ground truth. Compute word error rate (WER) via `jiwer` or a simple `difflib.SequenceMatcher` ratio. Record per-segment diffs so we can characterise the kinds of errors each recipe makes (homophones, dropped lines, repeated chorus, etc.).

## How to run

```bash
bash pocs/30-whisper-timestamped/scripts/run.sh
```

## What gets written

- `outputs/timestamped.json` — variant M raw output
- `outputs/timestamped.txt` — variant M plain transcript
- `outputs/whisperx-noprompt.json` — variant W raw output
- `outputs/whisperx-noprompt.txt` — variant W plain transcript
- `outputs/comparison.md` — side-by-side WER + sample diffs vs ground truth
- `outputs/install.log` — proof of clean install
- `outputs/stdout-{m,w}.log` — full run logs

## After running

Fill `RESULT.md` with: install status, wall times, WER per variant, characterisation of remaining errors, recommendation for story 14.
