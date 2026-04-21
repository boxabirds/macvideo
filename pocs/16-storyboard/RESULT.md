# POC 16 — RESULT

**Status:** not yet run

**Date run:** _fill_

## Pathological test

Three identical target lines (`["He's arrived again"] × 3`) — does Pass C produce three *distinct* progressive beats?

- [ ] Pass C returns 3 different `beat` values
- [ ] 3 keyframes are visibly different moments (same character + setting by identity chain, different action/state)
- [ ] Sequence reads as establish → develop → culminate, not 3 copies
- [ ] Camera arc coherent across the 3 shots (no jarring reversals)
- [ ] LTX motion obeys each shot's `camera_intent` (push-in pushes in, static holds)

## Pass C storyboard (fill from storyboard.json)

- **sequence_arc:** _fill_

| Shot | beat | camera_intent | subject_focus | prev_link | next_link |
|---|---|---|---|---|---|
| 1 | | | | — | |
| 2 | | | | | |
| 3 | | | | | — |

## Observations

_Do the beats make narrative sense? Is the progression legible?_

## Camera arc check

_List adjacent-shot transitions. Any direction reversals (push→pull, pan-left→pan-right)? Justified or jarring?_

## Pathological test verdict

- **Beats distinct:** yes / no
- **Visuals distinct:** yes / no
- **Progression legible:** yes / no

## Decisions back to the main plan

- [ ] Pass C goes into Stage 4 (shot planner) ahead of per-line Pass B
- [ ] Camera-intent vocabulary: does the current 11-value list need tuning?
- [ ] Motion mapping lives in run.sh for now; move to config file in real pipeline

## Overall

**Result:** PASS / WEAK / FAIL
