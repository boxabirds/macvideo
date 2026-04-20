# POC 1 — RESULT

**Status:** not yet run

**Date run:** _fill in_

## Environment

- Hardware: _e.g. MacBook Pro M5 Max, 128 GB_
- macOS version: _fill in_
- `mlx-video` commit: `9ab4826d20e39286af13a26615c33b403d48be72`
- `uv` version: _fill in_

## Pass criteria

- [ ] `outputs/smoke.mp4` exists and plays
- [ ] Visual content matches prompt
- [ ] Wall time reasonable (second run, post-download)
- [ ] Help output captured
- [ ] Flag list reconciled against `docs/20260420-music-video-ltx23-mac.md` §4

## Measurements

- Weight download time (first run): _fill in_
- Generation wall time: _fill in_
- Peak RSS: _fill in_ (from `outputs/time.txt`)
- Output file size: _fill in_

## Flag drift

Compare `outputs/help.txt` against the flag list in the guide. Record any differences here:

- _e.g. `--output` confirmed / `--output` missing, replaced by `---`_
- _e.g. `--num-frames` accepted / rejected_
- _e.g. `--fps` accepted / rejected_
- _e.g. `--audio-file` accepted / rejected_
- _e.g. `--first-frame` / `--init-image` present? (relevant for POC 3, 4)_
- _e.g. `--negative-prompt` present? (relevant for prompt template design)_

## Surprises / errors

_free text_

## Decisions back to the main plan

If this POC revealed something that changes `docs/plans/20260420-initial-prototyping.md`, list the changes here before editing that doc:

- _e.g. "mlx-video does not expose --first-frame. POC 3 blocked until patched or we pick a different approach."_

## Overall

**Result:** PASS / FAIL / PARTIAL

_one-paragraph summary_
