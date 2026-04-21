# POC 3 — RESULT

**Status:** PASS

**Date run:** 2026-04-21

## Pass criteria

- [x] Frame 0 of output matches the reference still (composition, subject, palette)
- [x] Motion through the clip feels continuous, not a hard cut to different content
- [x] Prompt's motion direction (pull back / widen) is realised in the clip

## Measurements

- Wall time: 24.8 s (0.34 s/frame)
- Peak memory: 37.74 GB
- Output: 263 KB mp4, 73 frames, 512×320
- Pipeline: distilled (I2V works on distilled — contrary to what we might have inferred from POC 2's CFG-pipeline gap)

## Visual comparison

### Input `input.png`
Dark choppy sea, partial wreck listing mid-frame, distant horizon with faint structures, 16mm grain.

### Output frame 0 `frame_0.png`
Near-identical to input. Same wreck position, same horizon, same grain. Visually indistinguishable on first-glance inspection.

### Clip evolution (frames 0, 24, 48, 72)

- **f00** — matches input
- **f24** — wreck tilted lower-left, horizon gaining detail
- **f48** — wreck shrinks, large dark structure (building?) emerges on the right
- **f72** — wreck small and distant, building prominent, more sky — the "wide establishing shot" the prompt asked for

Motion direction (pull back) realised. New context (building, expanded horizon) hallucinated into the scene, which is exactly what we want from a text+image generation pair.

## Surprises

1. **I2V works on distilled** even though distilled has no CFG. The image-conditioning code path (`VideoConditionByLatentIndex` at `generate.py:2109`) is applied to the initial latent state, not as CFG guidance. So distilled can do I2V just fine — unlike audio or negative prompting, which require CFG to manifest.
2. **VAE encoder bug required a patched mlx-video.** Upstream `9ab4826` has the bug on LTX-2.3 weights (topology mismatch from LTX-2 block spec). Pinned to PR #24 HEAD (`a8cd1db7`) from [nopmobiel:fix/vae-encoder-ltx23-i2v](https://github.com/Blaizzy/mlx-video/pull/24). Revert to Blaizzy main once merged.

## Decisions back to the main plan

- [x] I2V flag behaviour confirmed: `--image` + `--image-strength` + `--image-frame-idx` all functional.
- [x] I2V works on distilled (iteration profile can use keyframes). This is stronger than the plan assumed.
- [x] Pin mlx-video to nopmobiel's fork commit until PR #24 merges upstream.
- [ ] Open: test `--image-strength` < 1.0 to see if partial conditioning produces useful blends. Not urgent.

## Overall

**Result:** PASS. I2V is a reliable primitive on distilled at iteration resolution. The keyframe-first architecture is viable: Gemini generates stills (POC 5 confirmed) → LTX I2V animates from them → clips get assembled. POC 4 (chained shots via previous clip's last frame) uses the same mechanism and the PR #24 author specifically tested 3-scene chaining, so it's likely to pass on the same infrastructure.
