# POC 14 — Abstraction slider (0–100)

**Goal:** Same lyric line, same world brief, same filter, rendered at five abstraction levels (0, 25, 50, 75, 100). Verify the dial produces a clean spectrum from literal to fully abstract, and that the pipeline can attach abstraction as a per-shot parameter.

## Pass criteria

- [ ] 5 keyframes produced, one per abstraction level
- [ ] Spectrum visible: 0 is literal, 100 is pure abstract; intermediate stops are meaningfully different from each other
- [ ] Filter (charcoal) holds across all levels — the medium doesn't collapse when the subject abstracts
- [ ] At N ≥ 75 identity chaining is skipped (no face to preserve)

## Method

- **Line:** `"He's arrived again"` (POC 13's opening line)
- **Filter:** `charcoal`
- **World brief:** regenerated via POC 13 Pass A with filter=charcoal (same path as the real pipeline)
- **Abstraction levels:** 0, 25, 50, 75, 100 — each mapped to a concrete descriptor, no named artists:

| N | Descriptor |
|---|---|
| 0 | fully representational, photographic clarity, subjects rendered as concrete recognisable form with grounded proportions and depth |
| 25 | loosely expressive — brushwork and line quality given primacy over accuracy; subjects still clearly legible but simplified; distortion and gesture honoured |
| 50 | heavily stylised — figures become simplified masses and volumes, architecture reduced to structural shapes; recognisable but abstracted |
| 75 | predominantly abstract — the figure becomes a dark mass or smear, the setting becomes rectangles of light and shadow, details replaced by rhythm and weight |
| 100 | pure abstraction — no recognisable figures, objects, or settings; composition is colour field, line, rhythm, texture |

Each level produces its own Pass B prompt, rendered by Gemini independently (no cross-level identity chain — we want the spectrum, not consistency).

## Prompt convention

Affirmative only. No content negatives. Pass B tells the LLM to describe what *is* present in the frame (materials, objects, atmosphere, motion) at the specified abstraction level — not what is absent.

## How to run

```bash
uv run python pocs/14-abstraction/scripts/run.py
```

~2–3 min (1 Pass A + 5 Pass Bs + 5 image calls, ~15–20 s each).

## Output

`pocs/14-abstraction/outputs/YYYYMMDD-HHMMSS-charcoal/`:
- `abstraction_000.png` ... `abstraction_100.png`
- `character_brief.json`
- `prompts.json` (Pass A input/output, per-level Pass B inputs, per-level image prompts)
