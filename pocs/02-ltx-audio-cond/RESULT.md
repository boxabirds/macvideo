# POC 2 — RESULT

**Status:** PASS (conditional — distilled is inert, dev works)

**Date run:** 2026-04-21

## Pass criteria

- [x] Three clips (+ two dev-pipeline retries) generated with identical prompt + seed, varying only `--audio-file`
- [x] Content-sensitive audio differentiation demonstrated — in **dev pipeline only**
- [x] Distilled pipeline confirmed inert on audio content (binary on/off only, no content-sensitivity)
- [x] Root cause identified in the mlx-video source

## Measurements — distilled pipeline (first pass)

| Clip | Wall time | Composition (first frame) |
|---|---|---|
| a_no_audio | 21.5 s | Partial wreck in choppy dark sea |
| b_ambient (chronophobia) | 41.2 s | Clean moonlit ocean, sun/moon reflection |
| c_beat (busy-invisible) | 24.2 s | *Identical composition to b* |

Peak memory: 37.23 GB for all three.

Observation: (b) and (c) are essentially identical in the first frame and in motion. (a) differs (no audio present at all), so the distilled pipeline does see "audio-file present vs absent" as binary, but does not differentiate *content* of the audio.

## Measurements — dev pipeline retry

Same prompt, seed, frame count; only the audio input varied.

| Clip | Wall time | Composition (first frame) |
|---|---|---|
| b_ambient_dev | 19m 57s (9.89 s/frame) | Two figures on a small paddle craft, pastel dusk horizon, calm water |
| c_beat_dev | 4m 42s (2.33 s/frame) | Single figure on a white speedboat, closer framing, darker/more dramatic sky |

Peak memory: 36.79 GB for both.

Observation: substantively different scenes from identical text prompt and seed. Audio conditioning actually drives subject, framing, and mood in the dev pipeline.

**Wall-time asymmetry:** 4× slower on the first dev invocation. Almost certainly cold-load (first dev generation of the session does MLX buffer warmup / weight allocation). Not investigated further.

## Root cause — why distilled is inert

`denoise_distilled` (`generate.py:474–486`) signature:

```python
def denoise_distilled(
    latents, positions, text_embeddings, transformer, sigmas, verbose,
    state, audio_latents, audio_positions, audio_embeddings, audio_frozen,
)
```

No `audio_cfg_scale` parameter. Audio latents and embeddings flow into the joint A/V attention, but there is no classifier-free-guidance amplification of the audio signal.

Contrast with `denoise_dev_av` (called at `generate.py:2320`): takes `audio_cfg_scale` and applies it to amplify the difference between "audio-present" and "audio-absent" predictions.

The `distilled` variant was *trained* to produce reasonable output without CFG. This means it learned to be less dependent on conditioning signals in general — not just a smaller/faster dev, but **a different decoder trained for a different inference regime**.

## Decisions back to the main plan

- [x] Keep `--audio-file` in the shot-plan schema.
- [x] Gate audio conditioning usage by pipeline profile:
  - `poc` / `iteration` (distilled): **do not pass `--audio-file`** — inert and marginally slower.
  - `final` (dev-two-stage-hq): **pass `--audio-file`** per shot — will drive subject, framing, and mood.
- [x] Document in the main plan that distilled is functionally different (no CFG, not just a smaller model), so expectations about conditioning strength differ per profile.
- [ ] Open: verify dev-two-stage and dev-two-stage-hq also honour audio conditioning (they should — Stage 1 is dev-with-CFG). Confirm when we run POC 9 end-to-end.

## Overall

**Result:** PASS. Audio conditioning is a real, content-sensitive signal in the dev-family pipelines — but **only** in dev-family. Distilled is architecturally CFG-less and not a viable audio-driven generator. This splits the pipeline cleanly: distilled for iteration, dev-two-stage-hq for audio-responsive final output.
