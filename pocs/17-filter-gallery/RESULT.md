# POC 17 — RESULT

**Status:** running in background

**Date started:** 2026-04-21

## What this produces

- 3 songs × ~26 filters = ~78 combos
- Each combo: Pass A brief + Pass B image prompt + Gemini keyframe + LTX I2V silent clip at 10 fps / 512×320 (~1.7 s)
- Live-updating `progress.html` in the run dir
- Final `gallery.html` when complete
- All prompts persisted to per-combo `prompts.json` for audit

## Estimated duration

~2–2.5 h for full run. Resumable — rerun skips combos whose `clip.mp4` already exists.

## After viewing the gallery

Promote every filter whose row looks good to `status: accepted` in `config/styles.yaml`. Demote any that collapse into other filters or produce mush to `rejected`. Everything else stays `proposed` pending further iteration.

## Overall

**Result:** _fill_ (after viewing the gallery)
