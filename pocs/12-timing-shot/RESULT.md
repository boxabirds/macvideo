# POC 12 — RESULT

**Status:** not yet run

**Date run:** _fill_

## Pass criteria

- [ ] Line picked and timing extracted from `aligned.json`
- [ ] Keyframe generated
- [ ] LTX I2V clip produced at exact num_frames matching line duration
- [ ] Sync test video plays — lyric and visual hit together within ±100 ms

## Timing for picked line

- Target text: _fill_
- Start: _fill_ s  End: _fill_ s  Duration: _fill_ s
- num_frames: _fill_  (at 24 fps = _fill_ s)
- Timing slop vs actual line duration: _fill_ ms

## Wall time

- Keyframe gen (Gemini): _fill_ s
- LTX I2V: _fill_ s
- Total: _fill_ s

## Sync assessment

Watch `outputs/sync_test.mp4`. When "That's my little blackbird" is sung, is the visual there, on time?

- Sync by ear: tight / loose / off (give ms estimate)
- Is the keyframe's imagery appropriate for the line?

## Decisions back to the main plan

- [ ] `num_frames = ((int(duration * fps) - 1) // 8) * 8 + 1` formula works
- [ ] Sync within ±100 ms confirms word-level timing is accurate enough to drive shots
- [ ] Deforum-style line-per-shot approach validated in the new pipeline

## Overall

**Result:** PASS / WEAK / FAIL
