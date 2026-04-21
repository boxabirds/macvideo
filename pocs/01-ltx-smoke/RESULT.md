# POC 1 — RESULT

**Status:** PASS

**Date run:** 2026-04-21

## Environment

- Hardware: MacBook Pro M5 Max, 128 GB unified memory
- OS: Darwin 25.4.0
- `mlx-video` commit: `9ab4826d20e39286af13a26615c33b403d48be72`
- Python: 3.11.11 (via uv)

## Pass criteria

- [x] `outputs/smoke.mp4` exists and plays
- [x] Visual content matches prompt (spot-checked; distilled pipeline output)
- [x] Wall time reasonable — 30.3 s is *dramatically* faster than the guide's 6–12 min claim
- [x] Help output captured in `outputs/help.txt`
- [x] Flag list reconciled against the guide

## Measurements

- **LTX-2.3-distilled weights:** ~56 GB on disk (48 files), download 26 min first time — **guide's "~19 GB" claim is wrong**
- **Gemma 3 12B bf16:** ~24 GB on disk (15 files), download 7 min
- **Generation wall time:** 30.96 s total, 30.3 s reported by the tool (0.42 s/frame)
- **Peak memory:** 37.11 GB (tool-reported) / 39.2 GB maximum RSS
- **Output:** 133 KB mp4, 73 frames @ 24 fps, 512×320

## Flag drift against `docs/20260420-music-video-ltx23-mac.md` §4

Discoveries from `outputs/help.txt`:

| Flag | Status | Notes |
|---|---|---|
| `--output-path` | ✅ correct | An earlier guide "correction" wrongly changed this to `--output` — reverted. `--output` is ambiguous with `--output-audio`. |
| `--image` + `--image-strength` + `--image-frame-idx` | ✅ present | I2V supported; `--image-frame-idx` allows conditioning at any frame — unblocks POC 3 and POC 4. |
| `--negative-prompt` | ⚠️ dev-only | Help says "Negative prompt for CFG (dev pipeline only)". Distilled can't use it. Matters for the prompt-template design in Stage 4. |
| `--audio-file` + `--audio-start-time` + separate `--audio` | ✅ present | Audio conditioning is first-class; `--audio` controls whether audio is decoded/saved. |
| `--num-frames` + `--fps` | ✅ present | **Constraint discovered:** num-frames must equal `1 + 8*k` (auto-bumped 72 → 73 in run). |
| `--enhance-prompt` + `--max-tokens` + `--temperature` | ✅ present | Built-in LLM prompt rewriter. Ignore for now; we own the prompt template. |
| `--spatial-upscaler` | ✅ present | Built-in upscaling option. Relevant for HQ pass. |
| `--stg-scale`, `--apg`, `--modality-scale`, `--cfg-rescale`, `--audio-cfg-scale` | ✅ present | Advanced guidance knobs; leave at defaults for now. |
| `--text-encoder-repo` | ✅ required | Not documented in the guide. Must pass `mlx-community/gemma-3-12b-it-bf16` explicitly — default behaviour looks in the main model repo and fails. |

## Surprises

1. **Hidden Gemma 3 12B dependency.** `mlx-video` uses `google/gemma-3-12b-it` as the hardcoded default text encoder — not mentioned anywhere in the LTX guide or the prince-canuma README that I reviewed. Google's repo is gated (early-access form); Gemma 4 is out, so the form is unlikely to be approved quickly. **`mlx-community/gemma-3-12b-it-bf16` is the MLX-native, non-gated drop-in.** Add this to Stage 0.
2. **`num-frames` must be `1 + 8*k`.** Any shot-duration calculation in Stage 4/5 must round to this. Formula: `num_frames = ((int((end_t - start_t) * fps) - 1) // 8) * 8 + 1`.
3. **Second MLX process = fatal.** Running another MLX workload (opencode-vllm-mlx in this case) caused `RuntimeError: [Event::Event] Failed to create Metal shared event` even after LTX's weights and text encoder loaded. Killing the competitor fixed it. See [mlx-lm issue #887](https://github.com/ml-explore/mlx-lm/issues/887). Add to the runbook: "quit every other MLX process before generation."
4. **Wall time is ~10–20× better than the guide's estimates.** Distilled 512×320 = 30 s, not 6–12 min. The guide's §13 table is stale by a wide margin and should be treated as "no signal" until re-benchmarked at higher resolutions.
5. **Distilled is internally a two-stage process** (256×160 → 512×320). Useful mental model for later — the "iteration profile" 896×512 will internally go through a smaller draft resolution first.

## Decisions back to the main plan

- [x] Close open question: `--output-path` confirmed
- [x] Close open question: `--negative-prompt` present but dev-only (prompt template must be aware)
- [x] Close open question: I2V conditioning exists (`--image`, `--image-frame-idx`)
- [x] Close open question: `mlx-video` CLI flags match the guide (mostly — reconciled above)
- [ ] **Revise wall-time expectations** in `docs/plans/20260420-initial-prototyping.md` and in the main guide's §13 table. Re-benchmark needed at `iteration` (896×512) and `final` (1920×1080) resolutions.
- [ ] **Add Gemma 3 12B bf16 to the Stage 0 setup checklist** as an explicit ~24 GB download and a runtime dependency.
- [ ] **Add "single MLX process at a time" to the runbook** in the main guide's troubleshooting section.
- [ ] **Document the `1 + 8*k` num-frames constraint** in the Stage 4 and 5 spec.

## Overall

**Result:** PASS. LTX-2.3 runs on M5 Max, the pipeline architecture is viable, and wall times are dramatically better than the guide claimed. Hidden dependencies (Gemma text encoder) and MLX process contention are captured for the next machine's setup. No blockers to continuing.
