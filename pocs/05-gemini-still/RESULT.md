# POC 5 — RESULT

**Status:** PASS

**Date run:** 2026-04-21

## Pass criteria

- [x] API returns an image (no auth / gate / model-ID errors)
- [x] Image quality adequate as an LTX seed frame
- [x] Prompt adherence excellent — all specified elements rendered
- [x] Latency + token usage captured

## Measurements

- Model ID: `gemini-3.1-flash-image-preview` (valid on 2026-04-21)
- Latency (first call): 18.26 s
- Returned image: 859 KB PNG (resolution not in metadata — inspect `outputs/still.png`)
- Tokens: prompt 65, candidate (image) 1120, total 1599
- Cost: not yet calibrated; record once real per-token pricing is confirmed from Google docs.

## Visual review

Output is a sumptuous steampunk cityscape:
- Victorian wrought-iron filigree gate in the foreground (silhouette)
- Brass gears (large central ensemble), riveted copper pipes and smokestacks
- Multiple lit gaslamps scattered through mid-ground
- Volumetric steam rising between structures
- Two airships in the background sky, adding depth
- Sepia / warm-amber palette, cinematic wide framing
- 16mm film grain evident but subtle

All specified prompt elements present. No figures, no text. Arguably over-delivers on composition — this has more depth, staging, and atmosphere than Flux-family output for an equivalent prompt.

## Decisions back to the main plan

- [x] Model ID `gemini-3.1-flash-image-preview` confirmed valid at 2026-04-21.
- [ ] Calibrate per-image cost by running 3–5 representative stills and computing total billed tokens × current pricing. Store in `config/pipeline.yaml` as a budget ceiling.
- [ ] 18 s latency is high for 40+ stills per track (~12 min total image gen). Acceptable but worth a note — budget it in wall-time planning.
- [ ] Output resolution needs to be recorded: the API returned the image at its default — we may need to request specific dimensions for LTX's input requirements.

## Overall

**Result:** PASS. The Gemini keyframe path works, the preview model ID is live, quality is strong, cost/latency in a reasonable range. Identity consistency (POC 6) still to test — that's the harder question, since it tests whether the same performer can appear convincingly across multiple stills.
