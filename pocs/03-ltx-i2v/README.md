# POC 3 — LTX-2.3 image-to-video from a static still

**Goal:** Verify I2V mode works: a supplied still becomes frame 0, motion unfolds from there with a different prompt than what produced the still. Tests whether `--image` (and `--image-strength`, `--image-frame-idx`) correctly anchor the generation on the reference.

## Pass criteria

- [ ] Output frame 0 visually matches the input still (within codec rounding)
- [ ] Subsequent frames evolve naturally — motion develops from the seed state
- [ ] Style does not mutate wildly — the aesthetic of the input still carries through
- [ ] Works on the distilled pipeline (we'll use distilled here since this unblocks iteration)

## Inputs

- Reference image: the first frame of POC 2's `a_no_audio.mp4` (dark wreck in choppy sea) — reused so we have a known visual we can compare against.
- Prompt *different* from what generated the still: `"slow pull back from the wreck, wide establishing shot emerging, overcast light, 16mm grain, no figures"`
- Seed: `42`
- Frames: `73` (1 + 8×9, ~3 s at 24 fps)

If frame 0 matches the wreck but later frames show a wider shot pulling back, the I2V flag is doing its job. If frame 0 is unrelated to the input or the content mutates into something other than a wreck scene, I2V is broken.

## How to run

```bash
bash pocs/03-ltx-i2v/scripts/run.sh
```

Expected wall time: ~30–60 s on M5 Max (distilled).

## What it generates

- `outputs/i2v.mp4` — the generated clip
- `outputs/frame_0.png` — extracted first frame of the output (for direct comparison)
- `outputs/input.png` — a copy of the reference image
- `outputs/stdout.log` — generation log

## After running

Open `input.png` and `frame_0.png` side by side in Preview. Record in `RESULT.md`:
- Is frame 0 a close match to the input? (byte-identical won't happen — look for composition and subject match)
- Does the motion through the clip feel continuous, not a hard reset?
- Any style drift or content replacement?
