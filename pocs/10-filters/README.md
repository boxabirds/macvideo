# POC 10 — Thematic filters produce visually distinct output

**Goal:** Prove the filter system delivers — same subject, five filter words (papercut, watercolour, steampunk, pencil sketch, bubblegum), visibly different aesthetics in the rendered images. If papercut and pencil sketch look the same, the filter taxonomy is collapsing and the pipeline's style-per-song mechanism is meaningless.

## Pass criteria

- [ ] 6 images produced (1 reference + 5 filtered)
- [ ] All 5 filters are visually distinct from each other
- [ ] All 5 filters are distinct from the reference
- [ ] Subject is still recognisable (stone bridge over water) — the filter is a lens, not a replacement of the content

## Method

1. One neutral subject prompt: a weathered stone bridge over dark peat-stained water.
2. For each filter word:
   - LLM (`gemini-3-flash-preview`) expands the filter to concrete visual cues (materials, lighting, palette, line quality).
   - Expansion is appended to subject prompt.
   - Image (`gemini-3.1-flash-image-preview`) renders.
3. Reference image generated from subject only, no filter.

## How to run

```bash
uv run python pocs/10-filters/scripts/run.py
```

~2–3 min total (5 LLM calls + 6 image calls, each image ~15–20 s).

## Output

- `outputs/00_reference.png` — subject only
- `outputs/01_papercut.png`, `02_watercolour.png`, `03_steampunk.png`, `04_pencil_sketch.png`, `05_bubblegum.png`
- `outputs/expansions.json` — the LLM-generated visual cues per filter (for reproducibility and iteration)
- `outputs/meta.json` — latencies, token counts
