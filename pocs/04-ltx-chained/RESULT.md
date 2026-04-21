# POC 4 — RESULT

**Status:** PASS

**Date run:** 2026-04-21

## Pass criteria

- [x] Clip B's first frame is (near-) identical to clip A's last frame — visually indistinguishable on direct inspection
- [x] No jump / flash / style shift at the seam
- [x] Chained output assembles cleanly via ffmpeg concat
- [ ] Full-speed playback of the seam — open `outputs/chained.mp4` in QuickLook and step through frames 72–73 to visually confirm (human-in-loop)

## Measurements

- Wall time: 2m 25.0 s (1.99 s/frame)
- Peak memory: 45.04 GB (higher than pure dev — stage 2 loads distilled LoRA on top)
- Pipeline: `dev-two-stage` — our newly-locked iteration profile
- Output: 234 KB `clip_b.mp4` + 496 KB `chained.mp4` (A+B concat)

**Speed comparison on identical shot parameters (512×320, 73 frames):**

| Pipeline | Wall time | Notes |
|---|---|---|
| distilled (POC 3) | 24.8 s | Fast but CFG-less |
| dev-two-stage (POC 4) | 2m 25 s | Our iteration profile |
| dev (POC 3 dev retry) | 4m 47 s | Full-stage CFG |

dev-two-stage ≈ 2× faster than pure dev, ~6× slower than distilled. Acceptable for iteration.

## Visual comparison

### last_frame_a.png (end of clip A)
Wreck in lower-left quadrant, large dark building/structure on the right, faint horizon, grainy 16mm look.

### frame_0_b.png (start of clip B)
Visually indistinguishable from last_frame_a.png. Same wreck, same building, same horizon, same grain. The encoder read the reference image at frame 0 exactly as intended.

## Decisions back to the main plan

- [x] **Chained shots confirmed viable on dev-two-stage.** Shot plan schema keeps the `chain_from_previous` flag; implementation is: extract last frame of previous clip → pass as `--image --image-frame-idx 0` to next shot.
- [x] Wall-time expectation for `iteration` profile (dev-two-stage) locked at ~2–3 min per 73-frame shot at 512×320.
- [ ] Open: test chaining across **3+ shots** (POC 4 only chained 2). Error compounds? Style drift over 5–10 linked shots? Revisit at POC 9 or as a separate micro-test.

## Overall

**Result:** PASS. The keyframe-first pipeline's two main wiring primitives — **I2V from a fresh keyframe** (POC 3) and **chain from a previous clip's last frame** (POC 4) — both work on dev-two-stage at iteration speed. Combined with POC 6's identity consistency, the full arc of the generation stage is structurally unblocked.
