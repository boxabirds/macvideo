# POC 25 — RESULT

**Status:** not yet run

**Date run:** _fill_

## Pass criteria

- [ ] `--end-image` accepted; no VAE regression from PR #24 absence
- [ ] Clip with both-ends produces different output than control (start-only)
- [ ] Last frame of both-ends clip resembles the end keyframe
- [ ] Interpolation reads as coherent motion, not abrupt cut

## Observations

_after watching ab.html_

## Decisions back to the main pipeline

- [ ] Adopt first+last-frame conditioning for long camera moves: yes / no
- [ ] Keep PR #23 pin / merge it with PR #24 / wait for upstream merge
- [ ] Shot planner can emit `end_keyframe` as a first-class field: yes / no

## Overall

**Result:** PASS / WEAK / FAIL
