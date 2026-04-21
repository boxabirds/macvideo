# POC 17 — Filter gallery across every song × every filter

**Goal:** Visually evaluate every filter in `config/styles.yaml` (status `accepted` or `proposed`) against the first scene of every track in `music/`. Produces a live-updating progress HTML while running and a final gallery HTML for side-by-side comparison.

## What it does

1. **Ensures aligned.json exists for every song** in `music/` (runs Demucs + wav2vec2 forced alignment via POC 7's tooling if missing). Caches under `pocs/17-filter-gallery/cache/`.
2. **Picks the first lyric line** of each song from its `aligned.json`.
3. **For every (song, filter) combination:**
   - Pass A (LLM): world brief that renders the song entirely within this filter
   - Pass B (LLM): image prompt for this song's first line, honouring the brief
   - Gemini image (`gemini-3.1-flash-image-preview`): keyframe
   - LTX-2.3 I2V (dev-two-stage): ~1.7 s silent clip at 10 fps / 512×320 to keep compute bounded
4. **Updates `progress.html`** after every combo completes. Auto-refresh every 15 s — viewable while running.
5. **Writes `gallery.html`** at the end. Grid view: rows = filters, columns = songs. Click any thumbnail to play the clip.

## Compute

- Per combo: ~90 s (25 s LLM + 20 s image + 40 s LTX + overhead)
- 3 songs × ~26 filters = 78 combos
- **Expected total: ~2 hours**, budget 2.5–3 hours with Gemini retry variance.

Resumable: re-running skips any combo whose `clip.mp4` already exists.

## How to run

```bash
uv run python pocs/17-filter-gallery/scripts/run_all.py
```

Run in background; watch `outputs/latest/progress.html` in a browser.

## Output

`pocs/17-filter-gallery/outputs/YYYYMMDD-HHMMSS/`:
- `progress.html` — live status grid (auto-refresh while running)
- `gallery.html` — final gallery (produced at end)
- `run_state.json` — task list + status for programmatic inspection
- `<song>/<filter>/keyframe.png` — the generated still
- `<song>/<filter>/clip.mp4` — the short silent LTX clip
- `<song>/<filter>/prompts.json` — every prompt used for this combo
- `songs.json` — first-line info per song

`cache/<song>/` — per-song stems + aligned.json (reused across runs).
