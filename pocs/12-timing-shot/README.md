# POC 12 — Precise text-timing driven shot

**Goal:** Take a specific lyric line from `aligned.json` (POC 7 output), generate a keyframe + LTX I2V clip whose duration exactly matches the line's sung duration, overlay on the original track audio at the correct timestamp. Verify sync by eye/ear. Validates the Deforum-style "line-driven shot" approach at the heart of the pipeline.

## Pass criteria

- [ ] A specific lyric line is picked and its start/end extracted from `aligned.json`
- [ ] Gemini generates a keyframe matching the line's imagery
- [ ] LTX I2V produces a clip of matching duration (num_frames rounded to `1 + 8k`)
- [ ] Output video has the clip playing over the exact audio slice of the song where the line is sung
- [ ] Watching it: the visual "hits" when the line is sung — sync is within ±100 ms

## Method

1. **Pick a line.** Default: `"That's my little blackbird"` (line with clearest imagery + bridge to song title).
2. **Get timing** from `aligned.json`:
   - `start_t = first_word.start`
   - `end_t = last_word.end`
   - `duration_s = end_t - start_t`
   - `num_frames = round(duration_s * 24 / 8) * 8 + 1`
3. **Keyframe:** Gemini (`gemini-3.1-flash-image-preview`) renders a small black bird image in northern English moorland, 16mm grain.
4. **Clip:** LTX I2V (`dev-two-stage`) from the keyframe, `num_frames` duration.
5. **Sync check:** ffmpeg extracts the exact audio slice `[start_t, end_t + small_pad]` from the master WAV; combines with the generated clip. Output: `sync_test.mp4`.

## How to run

```bash
# Step 1 (Gemini, can run in parallel with other MLX work)
uv run python pocs/12-timing-shot/scripts/prep_keyframe.py

# Step 2 (LTX, needs MLX slot free)
bash pocs/12-timing-shot/scripts/run.sh
```

- Step 1: ~15–20 s (Gemini API call).
- Step 2: ~1–2 min (LTX I2V on dev-two-stage for a short clip, plus ffmpeg).

## Output

- `outputs/line.json` — picked line with timing + duration + frame count
- `outputs/keyframe.png` — Gemini keyframe
- `outputs/clip.mp4` — LTX I2V clip
- `outputs/audio_slice.wav` — exact audio slice from the master
- `outputs/sync_test.mp4` — final sync check (the video to watch)
