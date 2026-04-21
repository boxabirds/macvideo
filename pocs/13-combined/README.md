# POC 13 — Combined: line-timing × thematic filter × 3-scene cuts × identity chain

**Goal:** Three lyric-driven shots from one song, rendered through a single thematic filter, performer identity carried through via Gemini reference-chaining, concatenated with hard cuts and synced to the actual audio. Integrates POCs 6, 7, 10, 11, 12 into one end-to-end mini-pipeline.

## Pass criteria

- [ ] 3 keyframes generated, one per target line
- [ ] Performer is recognisably the same person across all 3 keyframes (POC 6 identity chain working alongside LLM pass-A character brief)
- [ ] Same thematic filter applied consistently across all 3
- [ ] Each LTX I2V clip is the right duration for its line (num_frames = `1 + 8k`)
- [ ] Hard-cut concatenation plays cleanly with correct audio sync
- [ ] `prompts.json` contains every prompt (two LLM passes per song + one image prompt per line + one LTX prompt per line + negative prompts)
- [ ] Each run goes into its own timestamped `outputs/YYYYMMDD-HHMMSS/` directory

## Architecture

```
Song: my-little-blackbird.wav + my-little-blackbird.txt + aligned.json
│
├── Pass A (LLM, once per song)
│     Input: full lyrics + chosen filter
│     Output: persistent character + world brief (same narrator, same domestic
│     setting, same blackbird visual identity, filter baked in)
│
├── 3 target lines selected (narrative arc across the song)
│
└── For each line:
      ├── Pass B (LLM, per line)
      │     Input: line + full lyrics + Pass A's brief + filter
      │     Output: contextual image prompt that references the persistent
      │     character/world
      ├── Gemini image gen
      │     First shot: prompt alone (unconditioned)
      │     Subsequent: prompt + prior keyframes as reference (identity chain)
      ├── LTX I2V
      │     Clip of exact duration for the lyric line, keyframe as image anchor
      └── Audio slice from master for line's [start, end]

Concat: 3 clips back-to-back, 3 audio slices back-to-back, combine.
```

## Lines picked

Narrative arc across the song:
1. `"He's arrived again"` — arrival, the opening moment
2. `"He settles in now, makes himself at home"` — settling / verse 2 domestic
3. `"Oh why won't you, little blackbird, just fly away"` — the chorus plea

(Lines are configurable in `scripts/prep.py`.)

## Filter

`charcoal` — passed POC 10, tonally suits the song (sombre, smudged, monochromatic). Configurable.

## How to run

```bash
# Step 1 (Gemini — LLM pass A, LLM pass B × 3, image gen × 3 with identity chain)
uv run python pocs/13-combined/scripts/prep.py

# Step 2 (LTX — I2V × 3, audio slice × 3, concat)
bash pocs/13-combined/scripts/run.sh
```

Each run produces `pocs/13-combined/outputs/YYYYMMDD-HHMMSS/` with:
- `prompts.json` — every prompt used
- `character_brief.json` — Pass A output
- `lines.json` — picked lines with timings
- `keyframe_01.png`, `keyframe_02.png`, `keyframe_03.png`
- `clip_01.mp4`, `clip_02.mp4`, `clip_03.mp4`
- `audio_slice_NN.wav` × 3
- `final.mp4` — the combined sequence

A `latest` symlink tracks the newest run.
