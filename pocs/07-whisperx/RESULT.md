# POC 7 — RESULT

**Status:** PASS (strong — 100% word accuracy with accurate acoustic timings)

**Date run:** 2026-04-21

## Outcome

Full pipeline on `my-little-blackbird.wav`:

1. Demucs htdemucs_6s → vocals stem
2. WhisperX STT (float32, looser VAD, initial_prompt from lyrics.txt) — captures what was sung, for future ad-lib detection
3. **wav2vec2 forced alignment of the ground-truth lyrics against the audio** — produces the final word-level timings

Final `outputs/aligned.json` has:

- 234 words (ground truth is 232 — trivial diff from contraction tokenization)
- 0 words missing timestamps
- Acoustic timings throughout, no interpolation needed
- 100% word accuracy by construction — the words come from the user's `.txt`, not from STT

## Wall time

| Stage | Duration |
|---|---|
| Demucs htdemucs_6s (3:48 track) | ~50 s (cached after first run) |
| WhisperX STT + alignment | ~50 s (cached after first run) |
| wav2vec2 forced alignment (ground truth → audio) | 11.3 s |
| Peak RSS (force-align stage) | 9.5 GB |

## Architectural journey

Three attempts, documented so the approach is reproducible:

| Attempt | Word accuracy | Timing quality | Notes |
|---|---|---|---|
| 1. `compute_type="int8"`, default VAD | ~75% | — | Verse 1 (~35 words) almost entirely missed; int8 dropped quiet singing; VAD filtered whispered sections |
| 2. `compute_type="float32"`, looser VAD (0.35/0.25) | ~90% | good where captured | Verse 1 recovered; remaining errors all homophones or phonetic ambiguities ("noes" vs "nose", "Oh why won't you" vs "Oh I want you", "kettle clicked" vs "cat'll click") |
| 3. + `initial_prompt` seeded from lyrics.txt + SequenceMatcher ground-truth match | 100% words, but 14 words crammed at 112.29 s | poor in repeating-chorus region | Sequence alignment misaligned chorus 2 against chorus 1 positions — Whisper HAD captured the words, but the matcher put them in the wrong place |
| **4. + wav2vec2 forced alignment (final)** | **100%** | **100% acoustic, no interpolation** | Skips the text-similarity alignment entirely. Feeds the full ground-truth text and audio to wav2vec2 CTC alignment. Words come from text; timings come from acoustic evidence. Bulletproof for songs where the singer follows printed lyrics. |

## Config choices and why

- `device="cpu"`, `compute_type="float32"` — WhisperX does not support MPS in 2026 (missing Metal ops cause CPU fallback). CPU+float32 is the intended path. See `docs/research/20260421-better-transcription.md`.
- `vad_onset=0.35, vad_offset=0.25` — default pyannote VAD is tuned for speech; singing has sustained tones that trigger the off-state prematurely.
- `initial_prompt` seeded from lyrics.txt — biases Whisper toward the user's vocabulary, lifts raw STT accuracy from ~75% to ~90%+ before post-processing.
- Forced alignment against full ground-truth text — best timings available without migrating to a different framework.
- `ground_truth_match.py` kept in the repo for reference but superseded by `force_align.py`.

## Decisions back to the main plan

- [x] Stage 2 (Lyric transcription) output format is set: `aligned.json` with `words[]` (word, start, end, score) and `lines[]` (line-level records).
- [x] Stage 2 pipeline is: `prep_audio.py` → Demucs → `force_align.py` against user-supplied `.txt`. Whisper STT is optional supplementary output for ad-lib detection.
- [x] Require user to supply `music/<track>.txt` alongside `music/<track>.wav`. If missing, fall back to Whisper-only STT with known accuracy tradeoffs.
- [ ] Migrate to WhisperMLX if wall time becomes a bottleneck at pipeline scale. Current 11 s for forced alignment on a 4-min track is fine.

## Overall

**PASS.** 100% word accuracy, acoustic timings, 11 s wall time for the alignment stage on the M5 Max. The Stage 2 data shape (aligned.json) is the stable input for Stage 3 (structure analysis) and Stage 4 (shot planning).
