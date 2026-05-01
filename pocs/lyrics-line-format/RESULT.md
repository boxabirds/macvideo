# Result - Gemini lyric line formatting

Run:

```sh
uv run python pocs/lyrics-line-format/format_lines.py
```

Input:

- `pocs/lyrics-line-format/no-mans-land.whisperx.json`
- source producer:
  `editor/server/pipeline/scripts/whisperx_transcribe.py`
- source audio:
  `pocs/29-full-song/outputs/no-mans-land/vocals.wav`
- source shape: WhisperX-style top-level `segments[]` with `text`, `start`,
  and `end`

Output:

- `pocs/lyrics-line-format/no-mans-land.lines.json`

Outcome:

- PASS for the preservation invariant.
- WhisperX produced 10 transcription segments, about 276 words.
- Gemini returned 46 lyric lines.
- Validation passed: joining the returned lines reproduces the exact input
  transcription after whitespace normalization.
- Line length summary: min 2 words, max 9 words, average 6.0 words.
- Short-line behavior appeared: 3 lines have 3 or fewer words.

Interpretation:

Gemini can perform the intended formatting task for this fixture: insert song
line breaks from the actual WhisperX JSON source structure without changing the
transcription text. This is useful as a candidate pre-step before scene
planning, but it still needs a product design for mapping formatted lines back
onto segment/word timings and splitting scenes.
