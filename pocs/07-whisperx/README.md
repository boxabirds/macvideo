# POC 7 — WhisperX word-level transcription on real vocals

**Goal:** Demucs-separate vocals from a real song, run WhisperX large-v3 + alignment, produce word-level timing JSON. Verify accuracy is high enough to drive shot-cut timing (±100 ms on spot-checks).

## Pass criteria

- [ ] Demucs isolates a clean vocals stem from the full mix
- [ ] WhisperX large-v3 transcribes the vocals stem
- [ ] Alignment produces per-word start/end timestamps
- [ ] Word accuracy ≥ 85% on a spot-check of 10–20 words
- [ ] Timing precision within ±100 ms on a spot-check of 5–10 words (check by ear: play the clip and the first syllable of the marked word should hit where the JSON says)

## Inputs

- Track: `music/my-little-blackbird.wav`
- Demucs model: `htdemucs_6s` (6-stem split — vocals, drums, bass, piano, guitar, other)
- Whisper model: `large-v3` on CPU with int8 compute (MPS support for WhisperX is historically flaky)

## How to run

```bash
bash pocs/07-whisperx/scripts/run.sh
```

Expected wall time:
- Demucs htdemucs_6s on a 3–4 min track: ~2–5 min on MPS, longer on CPU.
- WhisperX large-v3 on ~4 min of vocals: ~2–5 min on CPU int8.
- First run downloads model weights (~3 GB for Demucs htdemucs_6s, ~3 GB for WhisperX large-v3, ~1 GB for the alignment model).

## What it generates

- `outputs/vocals.wav` — isolated vocals stem (copied from Demucs output dir)
- `outputs/transcript.json` — WhisperX output with `words` (word-level) and `segments` (line-level)
- `outputs/transcript.txt` — plain-text transcript for eyeballing
- `outputs/stdout.log` — full log

## After running

- Read `transcript.txt` against the actual song. Count missed or wrong words. Record accuracy %.
- Pick 5–10 words from across the song, open `vocals.wav` in QuickTime / Audacity, scrub to the JSON-reported start time for each. Is the word hitting that time ±100 ms?

Fill findings into `RESULT.md`.
