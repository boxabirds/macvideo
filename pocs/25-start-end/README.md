# POC 25 — First + last frame conditioning via PR #23

**Goal:** Test whether LTX-2.3 can interpolate smoothly between a supplied start keyframe and end keyframe, enabling controlled long camera moves and narrative transitions across a single clip.

## Pass criteria

- [ ] `--end-image` flag accepted by CLI (PR #23)
- [ ] Clip generates without crashing (VAE bug from PR #24 doesn't reappear on this branch)
- [ ] Frame 0 of output matches the start keyframe
- [ ] Last frame of output matches (or closely resembles) the end keyframe
- [ ] Intermediate frames show coherent interpolation between the two
- [ ] Compared to single-start (no end-image) control: end-conditioned version has a defined destination, unconditioned version drifts freely

## Method

- **Start keyframe:** `pocs/13-combined/outputs/latest/keyframe_01.png` (charcoal narrator, bird arriving on shoulder)
- **End keyframe:** `pocs/13-combined/outputs/latest/keyframe_03.png` (charcoal narrator, bird settled, tea mug visible)
- Both from the same POC 13 run — same character, same setting, same filter, different moment.

Two LTX generations at identical params (dev-two-stage, 512×320, 73 frames / 3.04 s at 24 fps, seed 42):

1. **Control:** `--image start_keyframe` only (no end conditioning). LTX freely generates motion.
2. **End-conditioned:** `--image start_keyframe --end-image end_keyframe`. LTX must land on the end frame.

## Inputs

Pinned mlx-video: `zhaopengme/mlx-video@a2046415` (PR #23 HEAD). Installed by `uv sync` after pyproject update.

## How to run

```bash
bash pocs/25-start-end/scripts/run.sh
```

Two sequential LTX runs, ~5 min total on dev-two-stage at 512×320.

## Output

`pocs/25-start-end/outputs/YYYYMMDD-HHMMSS/`:
- `start.png`, `end.png` — the two keyframes (copied for reference)
- `control.mp4` — only start-conditioned
- `both_ends.mp4` — both start + end conditioned
- `frame_00_control.png`, `frame_last_control.png` — first & last frame of control clip
- `frame_00_both.png`, `frame_last_both.png` — first & last frame of end-conditioned clip
- `ab.html` — side-by-side comparison page
- `prompts.json` — what was passed to LTX
