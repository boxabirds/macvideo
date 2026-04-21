# POC 4 — LTX-2.3 chained shots (last-frame → first-frame continuity)

**Goal:** Generate clip B whose first frame is clip A's last frame, producing frame-exact continuity across a cut. Confirms the "chain" pathway in the shot plan: `chain_from_previous: true` shots concatenate without visible seams.

## Pass criteria

- [ ] Clip B's first frame is (near-) identical to clip A's last frame — codec rounding is allowed, but no jump, flash, or style shift
- [ ] Motion in clip B feels like a continuation of clip A's motion, not a reset
- [ ] Style (grain, palette, subject) carries through the seam

## Inputs

- Clip A: reuse `pocs/03-ltx-i2v/outputs/i2v.mp4` — the wreck-pullback clip already confirmed good.
- Last frame of clip A is extracted to `inputs/last_frame.png`.
- Clip B prompt: `"camera continues pulling back, revealing the shoreline and stormy sky, overcast light, 16mm grain, no figures"`
- Pipeline: `dev-two-stage` (iteration profile locked in 2026-04-21).

## How to run

```bash
bash pocs/04-ltx-chained/scripts/run.sh
```

Expected wall time: ~1–2 min on dev-two-stage at 512×320, 73 frames.

## What it generates

- `outputs/last_frame_a.png` — last frame of clip A (the chain source)
- `outputs/clip_b.mp4` — the new clip, conditioned on that frame
- `outputs/frame_0_b.png` — first frame of clip B (for direct comparison)
- `outputs/chained.mp4` — A + B concatenated for seamless-playback review
- `outputs/stdout.log` — generation log

## After running

Open `chained.mp4` and watch full-speed. Then step through the A→B boundary frame-by-frame in QuickLook (right-arrow key).

Fill in `RESULT.md` with:
- Is the seam invisible at full-speed playback?
- Frame-stepping at the boundary: clean or jump?
- Does clip B's motion continue coherently from clip A's?
