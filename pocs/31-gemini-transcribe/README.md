# POC 31 — Gemini for sung-vocal transcription

## Question

Does Gemini's native multimodal audio input transcribe sung lyrics
materially better than our current WhisperX large-v3 baseline (87.5%
word accuracy on `my-little-blackbird`)?

This is a Pass-1 candidate for story 14 (audio-only transcription
when no `lyrics.txt` exists). If Gemini wins by ≥3 percentage points
on this fixture, it becomes worth re-measuring on `busy-invisible`
and `chronophobia` and considering as the default Pass 1.

## Why Gemini

- Already a project dependency (`google-genai>=1.0.0` in
  `pyproject.toml`); already used by the editor's filter chain.
- Native multimodal: audio in, text out, no separate STT model load.
- Long-form support documented up to 9.5 hours of audio per prompt.
- 38 MB stem fits via the Files API (over the 20 MB inline cap).

## What it cannot do (compared to whisper-family)

Per Gemini docs, the API does not return word-level timestamps in
its native transcription path. For story 14's two-pass architecture
this is fine — Pass 2 (wav2vec2 forced alignment via POC 07's
`force_align.py`) provides the per-word timings from Gemini's plain
text output. Pass 1 only needs to deliver accurate words.

## Recipe

- Model: `gemini-2.5-pro` (Pro tier — chosen for accuracy over
  Flash's lower latency/cost; this POC is about ceiling, not speed).
- Input: htdemucs_6s vocals stem
  (`pocs/07-whisperx/stems/htdemucs_6s/my-little-blackbird/vocals.wav`).
  Same stem POC 30 used, so the comparison is apples-to-apples vs
  WhisperX large-v3.
- Upload via Files API (file > 20 MB inline cap).
- Prompt: explicit verbatim-only instruction; no section markers, no
  commentary, plain text only.
- Output JSON shape mirrors WhisperX no-prompt — single segment with
  the full transcript text — so POC 30's `compare.py` works unchanged.

## Compared against

- Variant W (existing baseline): WhisperX large-v3, no
  `initial_prompt`, htdemucs_6s vocals. From POC 30:
  87.5% word accuracy / 12.5% WER, 40 s wall.
- Ground truth: `music/my-little-blackbird.txt` (232 words after
  cleaning).

## Pass criteria

- **PASS** if Gemini's word accuracy ≥ 90.5% (≥3 pp lift over
  WhisperX baseline). Justifies running on the other two checked-in
  songs.
- **MARGINAL** if 87.5–90.5%. Within noise of one fixture; not worth
  switching the default but flag for re-test if ground-truth-less
  songs accumulate.
- **FAIL** if < 87.5%. WhisperX stays as the story-14 Pass 1.

## Files

```
pocs/31-gemini-transcribe/
├── README.md (this)
├── RESULT.md (written after the run)
├── scripts/
│   ├── transcribe_gemini.py
│   └── run.sh
└── outputs/
    ├── gemini.json        ← Gemini transcript + metadata
    ├── gemini.txt         ← plain transcript for eyeballing
    ├── stdout.log         ← run log
    └── comparison.md      ← side-by-side vs WhisperX vs GT
```

## Reusing POC 30 outputs

This POC does NOT re-run WhisperX. It reads
`pocs/30-whisper-timestamped/outputs/whisperx-noprompt.json` as the
baseline B. If POC 30's outputs are missing, run
`bash pocs/30-whisper-timestamped/scripts/run.sh` first.
