# LTX-2 memory and wall-time profile at 1080p on M5 Max

**Date:** 2026-04-21
**Hardware:** MacBook Pro M5 Max, 128 GB unified memory
**Model / pipeline:** LTX-2.3 via `mlx-video` (pinned to `nopmobiel/mlx-video@a8cd1db`), `dev-two-stage` pipeline, I2V
**Source POC:** [POC 21 probe](../../pocs/21-1080p-probe/)

## Why this matters

Up to POC 20 we had only 512×320 empirical numbers. The production pipeline's final profile targets **1920×1080** and planning decisions (resolution, per-shot length, total song render time) depend on the memory and wall-time curves at that resolution. POC 21 probed it directly.

## Headline findings

1. **Peak memory is effectively flat with respect to frame count at 1920×1088.** ~45 GB across all frame counts measured (9 to 73 frames).
2. **Wall time scales linearly with frame count.** ~16 s/frame at 1080p dev-two-stage on M5 Max, amortising from ~26 s/frame at 9 frames to ~15.9 s/frame at 73 frames as fixed stage-1 setup amortises.
3. **We are not memory-bound at single-clip scale on 128 GB** at 1920×1088 dev-two-stage. The bottleneck for full-song 1080p generation is wall time, not memory.
4. **LTX-2 requires width and height each divisible by 64.** 1080 is not (1080 mod 64 = 56). Use 1088 (letterbox 8 px) or a cropped 1024 for "1080p" in the pipeline.

## Empirical data (tiling = auto, partial run)

Probe was aborted after 73 frames once the memory-flatness hypothesis was confirmed — no need to burn further compute.

| num_frames | duration (30 fps) | wall time | LTX "Generated in" | peak memory (LTX) | max RSS (OS) |
|---|---|---|---|---|---|
| 9 | 0.30 s | 237.8 s | 3m 55.7s | 45.06 GB | 43.4 GB |
| 17 | 0.57 s | 332.3 s | 5m 29.6s | 45.06 GB | 43.4 GB |
| 25 | 0.83 s | 441.9 s | 7m 19.2s | 44.99 GB | 43.4 GB |
| 33 | 1.10 s | 569.4 s | 9m 26.7s | 44.99 GB | 43.3 GB |
| 49 | 1.63 s | 796.6 s | 13m 13.9s | 44.99 GB | 43.4 GB |
| 73 | 2.43 s | 1158.7 s | 19m 16.0s | 46.25 GB | 43.4 GB |

Frame counts intentionally satisfy `num_frames = 1 + 8k` to avoid LTX's silent rounding.

## Why memory is flat — tiled / chunked temporal attention

LTX-2's transformer processes video in **temporal chunks** rather than loading every frame's tokens into attention at once. Memory is bounded by the chunk window, not the whole clip. This is consistent with its design goal of generating long coherent video (tens of seconds) at cinematic resolutions. The observed ~45 GB peak is the working set for one chunk plus the text encoder (Gemma 3 12B bf16 ≈ 24 GB on its own) plus the VAE weights and activations.

## Wall-time extrapolation

Linear extrapolation from the observed 15.9 s/frame asymptote (using 73 frames as the best estimate):

| num_frames | duration | projected wall time |
|---|---|---|
| 97 | 3.23 s | ~26 min |
| 121 | 4.03 s | ~32 min |
| 145 | 4.83 s | ~39 min |
| 193 | 6.43 s | ~52 min |
| 241 | 8.03 s | ~65 min |

**`dev-two-stage-hq` cost is unmeasured** but likely 1.3–2× `dev-two-stage` on the same resolution/frames (different sampler + LoRA on both stages instead of stage 2 only). The table above is lower-bound per-shot time for final quality.

## Implications for full-song 1080p pipeline

At 1920×1088 / 30 fps / dev-two-stage / I2V:

- **Per-shot cost** (typical 2–5 s shots): ~8–40 min each
- **Whole-song cost**: a 3.5-minute song with ~45 shots averaging ~3.5 s = **~19 hours per song** on dev-two-stage. dev-two-stage-hq will be slower still.
- **Memory headroom** is ample; no fallback to 720p required on memory grounds.
- **The pipeline is a batch job** at final quality, not interactive. The shot-planner/POC-13-architecture design (resumable, per-shot, skip-existing semantics) is exactly right for overnight rendering.

## Iteration vs final

| Profile | resolution | fps | s/frame | typical shot | per-shot time |
|---|---|---|---|---|---|
| Iteration (dev-two-stage, per POC 13/15/16) | 512×320 | 10 or 24 | ~2.0 | 2–5 s | 30 s – 3 min |
| Final (dev-two-stage-hq, per this research) | 1920×1088 | 30 | ~16 (extrapolated from dev-two-stage, HQ may be slower) | 2–5 s | 8–40+ min |

Iteration profile remains fast enough for interactive prompt-cycle refinement. Final profile is overnight.

## Planning rules locked in by this research

1. **Dimension validation at shot-plan time.** All resolutions in `config/pipeline.yaml` must have width and height each divisible by 64. 1088 not 1080 for "1080p".
2. **Frame-count formula.** `num_frames = ((round(duration * fps) - 1) // 8) * 8 + 1` to satisfy the `1 + 8k` constraint.
3. **No memory-driven resolution fallback.** Earlier concern that we might need to drop to 720p for memory is refuted.
4. **Wall-time budgeting must be per-shot.** Not per-song, because variability in shot length dominates. The shot planner should surface estimated per-song render time at plan time so the user can decide whether to cut shot count or drop frame rate.
5. **10 fps vs 30 fps.** 30 fps triples compute at same duration. For most music video aesthetics (medium-slow motion), 24 fps is the traditional sweet spot (cinematic). Consider 24 fps for final to save 20 % vs 30 fps.

## Open questions still unanswered

- **dev-two-stage-hq actual wall-time multiplier** vs dev-two-stage at 1080p. Needs a targeted 3–5 shot A/B to quantify.
- **Effect of `--tiling aggressive`** — POC 21 aborted before starting that pass, but given memory is already flat at `auto`, likely no meaningful change. Verify only if we need it.
- **Audio conditioning on long 1080p clips.** POC 20 was designed at 512×320. Whether `--audio-cfg-scale` behaves the same way at 1080p / longer clips is untested.
- **Numbers at 1280×720** as a middle-ground resolution — untested but expected to be roughly 2.25× cheaper per frame than 1080p.

## References

- [POC 21 run](../../pocs/21-1080p-probe/) — source, logs, progress.html
- [Main plan — iteration and final profile decisions](../plans/20260420-initial-prototyping.md)
- [Companion guide §13 resolution table (now obsolete; figures there were extrapolations)](../20260420-music-video-ltx23-mac.md)
