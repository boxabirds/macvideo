# POC 26 — Fake Deforum camera moves via start+end conditioning

**Goal:** Prove that LTX (with PR #23's start+end keyframe conditioning) can produce Deforum-style geometric camera motion by supplying the *same* content for start and end — but with the end frame geometrically transformed (zoomed 5%, rotated 15°). LTX is forced to interpolate that transform frame-by-frame, giving the perceived effect of a continuous zoom+rotate camera move.

## Pass criteria

- [ ] End-image generation: clean zoom-5%, rotate-15° of the start image
- [ ] LTX clip generates both frames and interpolates between them
- [ ] Intermediate frames show clear zoom progression + rotation progression (not a cut)
- [ ] No visible black corners from rotation in the output (zoom crops them out)
- [ ] Visual quality holds through the transform

## Method

1. Load a Gemini-generated keyframe (same narrator-at-table image from POC 13)
2. Generate end image programmatically:
   - Rotate 15° counter-clockwise (PIL, `expand=False`, black fill)
   - Zoom 5%: center-crop to ~95.2% of original dims, resize back to original
   - Combined effect: rotated AND zoomed-in; zoom crop hides rotation's corner fringes
3. Run LTX `dev-two-stage` with `--image=start` and `--end-image=end_transformed`
4. Extract frames 0, mid, last for comparison

## Why this matters

If this works, we get **Deforum's signature camera moves as a native LTX primitive**:
- Slow continuous zoom → define end image as slightly zoomed version of start
- Dolly-rotate → rotate + zoom the end image
- Pan → translate the end image
- Beat-synced pulses → chain very short clips with small transform deltas

No ffmpeg post-processing needed for the geometric motion itself. LTX paints every intermediate frame with real content, not cropped existing pixels — solving the "run out of canvas" problem that Deforum solved via img2img hallucination.

## How to run

```bash
uv run python pocs/26-deforum-fake/scripts/run.py
```

~3 min on dev-two-stage.

## Output

`pocs/26-deforum-fake/outputs/YYYYMMDD-HHMMSS/`:
- `start.png`, `end.png` — input keyframes (end is transformed start)
- `clip.mp4` — the generated 3 s clip
- `frame_00.png`, `frame_36.png`, `frame_72.png` — first, mid, last frames
- `view.html` — quick inspection page
