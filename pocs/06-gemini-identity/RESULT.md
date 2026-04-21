# POC 6 — RESULT

**Status:** PASS (strong)

**Date run:** 2026-04-21

## Pass criteria

- [x] All 5 stills returned successfully
- [x] Performer reads as the same person across all 5 — identity stability is essentially perfect
- [x] No visible drift at shots 3, 4, or 5
- [x] Bonus: *environment* continuity was maintained (boat name "SEA FARER" appears in both bow and cabin shots; mariner's distinguishing features stable across all scenes)

## Measurements

| Shot | Scene | Latency | Bytes | References used |
|---|---|---|---|---|
| 01_bow | trawler bow | 12.12 s | 902 KB | 0 |
| 02_pub | harbour pub | 12.52 s | 707 KB | 1 |
| 03_cliff | cliff path | 20.93 s | 817 KB | 2 |
| 04_cabin | trawler cabin | 11.22 s | 813 KB | 3 |
| 05_lane | village lane | 24.22 s | 979 KB | 4 |

**Total:** ~81 s for 5 stills, avg ~16 s/still.

**Latency does not grow monotonically with reference count** — shot 4 (with 3 references) was faster than shot 3 (with 2). API variability rather than a clear chaining cost.

## Pairwise similarity (1 = same person, 5 = clearly different)

All pairs ≈ 1 on visual inspection. Same beard pattern, same facial lines, same blue eyes, same build, same weathered jacket (minor wardrobe variation scene-appropriate: rain gear on the cliff, different beanie in the village lane).

## Drift observations

No drift. Identity stable across all 5 shots even at shot 5 (4 prior reference images). Minor wardrobe variations (different beanies, jacket swapped for hooded raincoat on the cliff) are scene-appropriate, not drift.

## Prompt-adherence nit

"No text" was in every prompt. The boat in shots 1 and 4 nonetheless has "SEA FARER FY147" rendered on it. Minor. Future pipeline prompts may need to be more emphatic about text suppression, but this is a small issue.

## Decisions back to the main plan

- [x] **Keep Gemini chained-refs for cross-shot identity.** This is the exact behaviour we switched to Gemini for.
- [ ] **Shots-per-performer cap:** 5 confirmed fine; the upstream concern (drift after 5+) is untested. For real pipelines of 30–40 shots with a recurring performer, spot-check at shot 10, 20, 30 before committing. Simplest next test: extend this POC to 10 shots.
- [ ] **Budget:** avg 16 s/still and ~800 KB per image. For a 40-shot music video with hero performer in ~15 shots, identity-chained image gen cost is ~240 s of API time plus tokens. Non-trivial but manageable.
- [ ] **Text suppression** needs strengthening in the shot-plan prompts (explicit "no signage, no boat names, no signs, no writing").

## Overall

**Result:** PASS (strong). The single most important POC for the keyframe-first architecture, and it lands confidently. Gemini's native identity-chaining is the reason this pipeline is viable without a separate IP-Adapter stack, and POC 6 validates the premise.
