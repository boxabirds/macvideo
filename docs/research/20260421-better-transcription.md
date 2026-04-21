# Better speech-to-text and word alignment on Apple Silicon

**Date:** 2026-04-21
**Triggered by:** POC 7 accuracy dispute — initial WhisperX run missed Verse 1 of `my-little-blackbird.wav` and hit ~75% word accuracy. User had extensive prior WhisperX experience delivering much better, correctly called out that corners had been cut.

## Why we're looking at this

The pipeline needs word-level timing of lyrics to drive shot cuts. The user supplies the **ground-truth lyrics** as `music/<track>.txt`, so we have two distinct problems:

1. Getting timings accurate to ±100 ms.
2. Getting the right words — a subset of the general transcription problem, since the words are already known from the .txt file.

The pipeline runs entirely on a MacBook Pro M5 Max with 128 GB unified memory. Ideally single-machine, no 4090 offload.

## What went wrong in the first POC 7 run

1. **`compute_type="int8"`** — aggressive quantization on `large-v3`. Dropped quiet/whispered sections entirely (Verse 1 of `my-little-blackbird.wav` captured only "Again" from ~35 expected words).
2. **Default VAD thresholds** (`vad_onset=0.5`, `vad_offset=0.363`) — too aggressive for singing. Voice activity detector filtered whispered vocals as non-speech.
3. **No `initial_prompt`** — model had no vocabulary priming, so sung idiosyncrasies ("noes" as plural of "no", "Oh why won't you") were replaced with acoustically-similar common words.
4. **No ground-truth post-processing** — homophones like `noes/knows/nose` cannot be disambiguated by audio alone. A correct transcript for a known song requires matching the STT output against the supplied lyrics.

Second run with `compute_type="float32"` + looser VAD (`0.35`/`0.25`) + explicit `language="en"` recovered Verse 1 cleanly and lifted word accuracy to ~90%. Wall time 51 s for a 4-min track — actually **faster than int8** (110 s) because int8 overhead dominated on CPU for the size class.

## Word-alignment options on Apple Silicon

| Option | Mechanism | Word accuracy | Speed | Notes |
|---|---|---|---|---|
| **WhisperX on CPU** ([m-bain/whisperX](https://github.com/m-bain/whisperx)) | Whisper STT + wav2vec2 forced alignment | High with proper settings; ~90% before post-processing, 100% after ground-truth match | ~51 s for 4-min track at `float32` on M5 Max | Current choice. MPS is not supported — missing Metal ops cause CPU fallback regardless. Not a corner-cut; it's the documented state of WhisperX on Apple Silicon. |
| **WhisperMLX** ([KalebJS/whispermlx](https://github.com/KalebJS/whispermlx)) | WhisperX fork with `mlx-whisper` as the STT backend | Same as WhisperX (keeps the wav2vec2 alignment step) | ~5–10× faster than WhisperX/CPU | Closest drop-in upgrade. Worth migrating to if wall time becomes a bottleneck at pipeline scale. |
| **ctc-forced-aligner** ([MahmoudAshraf97/ctc-forced-aligner](https://github.com/MahmoudAshraf97/ctc-forced-aligner)) | Pure CTC forced alignment (Wav2Vec2 / HuBERT / MMS) — no STT at all | 100% word accuracy (words come from supplied text) | Moderate, CPU or MPS via PyTorch | Clean for our use case: we have the lyrics, we just need timings. No STT errors possible because there's no STT. |
| **speech-swift** ([soniqo/speech-swift](https://github.com/soniqo/speech-swift)) — Qwen3-ForcedAligner | MLX-native forced alignment | "< 6 ms timing MAE, 100% text match rate" on LibriSpeech (per project claims) | Fast (MLX-native) | Newer, less battle-tested. Worth revisiting if ctc-forced-aligner proves slow. |
| **lightning-whisper-mlx** ([mustafaaljadery/lightning-whisper-mlx](https://github.com/mustafaaljadery/lightning-whisper-mlx)) | Fast MLX Whisper STT | — | 10× faster than whisper.cpp | **Does NOT support word-level timestamps or forced alignment.** README lists only: Batched Decoding, Distilled Models, Quantized Models, Speculative Decoding. Not useful for this pipeline. |
| **mlx-qwen3-asr** ([moona3k/mlx-qwen3-asr](https://github.com/moona3k/mlx-qwen3-asr/)) | Qwen3-ASR on MLX | High (Qwen3-ASR is state-of-the-art for singing per industry reports) | Fast | Potentially best singing ASR of the bunch. Alignment support needs verification. |

## The case for a hybrid: STT + ground-truth post-processing

Given we have the lyrics as `.txt`, two approaches give 100% word accuracy:

- **A. Pure forced alignment** — skip STT entirely. Feed `(audio, lyrics_text)` to CTC forced-aligner, get word timings. Simple, no STT errors possible.
- **B. WhisperX STT + ground-truth match** — run Whisper (or WhisperMLX), then fuzzy-align its word list against the ground-truth text, substituting correct words while preserving Whisper's timings.

**A is simpler and cleaner** when the singer follows the printed lyrics exactly.

**B is more robust** when the singer ad-libs, repeats, or deviates. Whisper still catches the ad-lib; the fuzzy match keeps Whisper's output for unmatched sections.

For this project's songs (user writes both lyrics and performance), deviations are expected to be minor. **A is probably enough.** B is a drop-in upgrade if edge cases appear.

## Decisions

1. **Stay on WhisperX for now** — it works, 51 s for a 4-min track is fine for the pipeline. No migration to WhisperMLX or MLX-native yet. Revisit only if wall time becomes a real bottleneck.
2. **Always use `float32`, never `int8`** for production runs. 128 GB of unified memory is plenty; int8 is a false economy.
3. **Looser VAD** (`vad_onset=0.35`, `vad_offset=0.25`) for singing. Default pyannote VAD is tuned for speech, and singing has longer held tones that trigger the off-state.
4. **Seed `initial_prompt` from the .txt file** for every track. Biases Whisper toward the user's vocabulary, directly fixing phonetic mishearings like "Oh why won't you" → "Oh I want you".
5. **Ground-truth post-processing step** after STT, using sequence alignment (e.g. `difflib.SequenceMatcher`) to substitute correct words while preserving Whisper's timings. This guarantees 100% word accuracy for any song where the user supplies `.txt`.
6. **Reconsider when:** batch transcription wall-time crosses ~30 s/track (switch to WhisperMLX); or singer deviates substantially from printed lyrics (switch to hybrid STT + match rather than pure forced alignment).

## References

- [m-bain/whisperX](https://github.com/m-bain/whisperx) — current pipeline component.
- [KalebJS/whispermlx](https://github.com/KalebJS/whispermlx) — WhisperX with MLX backend; future upgrade path.
- [MahmoudAshraf97/ctc-forced-aligner](https://github.com/MahmoudAshraf97/ctc-forced-aligner) — pure CTC forced alignment; alternate architecture.
- [mustafaaljadery/lightning-whisper-mlx](https://github.com/mustafaaljadery/lightning-whisper-mlx) — fast STT, no alignment (ruled out).
- [soniqo/speech-swift](https://github.com/soniqo/speech-swift) — MLX-native ASR + aligner toolkit.
- [mlx-qwen3-asr](https://github.com/moona3k/mlx-qwen3-asr/) — Qwen3-ASR on MLX.
- [Torchaudio forced alignment tutorial](https://docs.pytorch.org/audio/stable/tutorials/forced_alignment_tutorial.html) — reference for the CTC forced-alignment algorithm.
- [POC 7 result](../../pocs/07-whisperx/RESULT.md) — empirical measurements on `my-little-blackbird.wav`.
