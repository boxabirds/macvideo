# POC 30 — RESULT

**Status:** PASS for the install/run question; **FAIL for the "music2vid wins" hypothesis**.

**Date run:** 2026-04-25

## Headline

| Variant | Word accuracy | WER | Wall time | Words returned (GT=232) |
|---|---|---|---|---|
| M — whisper-timestamped medium + temperature ladder | **77.2%** | 22.8% | 234 s | 199 (33 deletions) |
| W — WhisperX large-v3, float32, no initial_prompt | **87.5%** | 12.5% | 40 s | 232 |

Tested on `pocs/07-whisperx/stems/htdemucs_6s/my-little-blackbird/vocals.wav` against `music/my-little-blackbird.txt` (232 words).

## Did the music2vid recipe still work in 2026?

Yes, technically. `whisper-timestamped 1.15.9` + `openai-whisper 20250625` install cleanly under `uv` on macOS Apple Silicon, Python 3.12. No code changes needed from the music2vid recipe.

But it loses to the existing WhisperX baseline by 10 percentage points of accuracy and runs ~6× slower.

## Where M loses words

33 deletions vs ground truth — entire short lines dropped, especially in the chorus's repeated "Just fly away" and the verse 2 "He pecks back / Persistent / Whispering again" sequence. The temperature-ladder fallback didn't recover them; whatever the VAD did, it ate them.

## Errors both variants make (the irreducible homophones)

- **noes → nose** (the song uses a deliberate plural of the word "no" — no model can know that without the .txt)
- **leaden → laden**
- **"why won't" → "i want"** (acoustic ambiguity in the chorus)
- **"I brush him" → "eye brushing"**

These are exactly the errors POC 07's RESULT.md called out. They will survive any audio-only transcription and are precisely why story 14's PRD demands a user-review step before the rest of the pipeline advances.

## Why M underperformed

Two factors compound:

1. **Model size: medium vs large-v3.** Medium has roughly half the parameters and is documented as substantially weaker on noisy/sung English. The temperature ladder is supposed to mitigate hallucination but doesn't recover dropped audio.
2. **Different VAD stacks.** whisper-timestamped's `vad=True` calls the `silero` VAD by default; POC 07's WhisperX uses `pyannote` with explicitly loosened onset/offset thresholds (0.35/0.25) tuned for sung audio. The default silero settings appear too strict — hence the 33 deletions.

The temperature ladder hypothesis (the original reason to revisit music2vid) didn't show up as a meaningful contributor here. WhisperX without it still beat whisper-timestamped with it.

## Wall time

- Variant M: 234 s (3.9 min) for ~3:48 of vocals on a 30 s WAV-equivalent of audio. Faster than POC 07's "~2–5 min" claim because the medium model is smaller. But still slow.
- Variant W: 40 s. Cached model load helped (large-v3 was already on disk from POC 07).

## Decisions back to story 14

1. **Use WhisperX large-v3 (no initial_prompt) for the audio-only transcription path.** It's the proven winner on this fixture by 10 pp. Same recipe as POC 07 with the prompt step removed.
2. **Keep the user-review-and-edit step in the story-14 PRD.** Even at 87.5%, the remaining 12.5% errors are the kind a human catches in seconds (homophones, ambiguous phrases) but a model never will from audio alone.
3. **Drop the temperature ladder as a hypothesis worth pursuing right now.** No evidence on this fixture that it helps. If story 14 ships with WhisperX and accuracy is reported as a problem in field use, revisit then.
4. **Don't add `whisper-timestamped` to project deps.** Removed. Dependency footprint stays small.
5. **Single-fixture caveat.** All numbers above are from one song. Before treating 87.5% as a SLA, run the same compare on `busy-invisible` and `chronophobia` (both have ground-truth `.txt` checked in). One-line config change in `run.sh`. Total wall time ~2 minutes per song with cached models.

## Suggested follow-up before story 14 starts

Run the comparison on the other two checked-in songs:

```bash
bash pocs/30-whisper-timestamped/scripts/run.sh busy-invisible
bash pocs/30-whisper-timestamped/scripts/run.sh chronophobia
```

Need the htdemucs_6s vocals stems for both first. If WhisperX maintains ≥85% across all three, the story-14 PRD's accuracy constraint is supportable. If accuracy drops sharply on one, document that and let the user-review step do the work.

## What got written

```
pocs/30-whisper-timestamped/
├── README.md
├── RESULT.md (this file)
├── outputs/
│   ├── comparison.md          ← side-by-side WER + diffs
│   ├── timestamped.json       ← variant M raw
│   ├── timestamped.txt        ← variant M plain transcript
│   ├── whisperx-noprompt.json ← variant W raw
│   ├── whisperx-noprompt.txt  ← variant W plain transcript
│   ├── stdout-m.log           ← variant M run log
│   ├── stdout-w.log           ← variant W run log
│   ├── time-m.txt             ← /usr/bin/time -l output
│   └── time-w.txt
└── scripts/
    ├── transcribe_timestamped.py
    ├── transcribe_whisperx_noprompt.py
    ├── compare.py
    └── run.sh
```
