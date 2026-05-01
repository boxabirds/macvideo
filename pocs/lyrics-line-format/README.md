# POC - Gemini lyric line formatting

## Question

Can Gemini take WhisperX transcription JSON and insert useful song lyric line
breaks without changing the transcription?

This POC tests line-break heuristics only. It is not a transcription cleanup
step and it must not rewrite, correct, add, remove, or reorder words.

## Input

Default fixture:

- WhisperX JSON: `pocs/lyrics-line-format/no-mans-land.whisperx.json`
- Required source shape: top-level `segments` array, where each segment has
  `text`, `start`, and `end`
- Fixture producer: `editor/server/pipeline/scripts/whisperx_transcribe.py`
  run against `pocs/29-full-song/outputs/no-mans-land/vocals.wav`

The script joins `segments[].text` in order into one normalized transcription
string before sending it to Gemini. There is no database fallback.

## Output

Default output:

```text
pocs/lyrics-line-format/no-mans-land.lines.json
```

Shape:

```json
{
  "song_slug": "no-mans-land",
  "model": "gemini-2.5-flash",
  "valid": true,
  "source": {
    "whisperx_json": "pocs/lyrics-line-format/no-mans-land.whisperx.json",
    "segment_count": 10
  },
  "lines": [
    { "line_index": 0, "text": "I left life on for years." }
  ]
}
```

## Validation

The validation is strict:

1. Normalize whitespace in the input transcription.
2. Join Gemini's returned line texts with spaces.
3. Normalize whitespace in that joined output.
4. Require exact string equality.

If validation fails, the output JSON includes the first differing character and
nearby snippets so the failure can be inspected.

## Run

```sh
uv run python pocs/lyrics-line-format/format_lines.py
```

To run a different WhisperX output:

```sh
uv run python pocs/lyrics-line-format/format_lines.py \
  --whisperx-json path/to/song.segments.json \
  --out path/to/song.lines.json
```

To regenerate the default source fixture:

```sh
uv run python editor/server/pipeline/scripts/whisperx_transcribe.py \
  --audio pocs/29-full-song/outputs/no-mans-land/vocals.wav \
  --out pocs/lyrics-line-format/no-mans-land.whisperx.json
```

The script loads `GEMINI_API_KEY` from the environment or project `.env`.
`EDITOR_GENERATION_MODEL` can override the default model.
