# POC 19 — Abstraction gallery per chosen filter per song

**Goal:** For every song in `music/`, using its filter chosen by POC 18, render the first scene at all 5 abstraction levels (0, 25, 50, 75, 100). Produces a 5-row × 3-column gallery so the user can see the abstraction axis for each song in its own approved visual vocabulary.

## Pass criteria

- [ ] POC 18 has run and produced a chosen filter per song
- [ ] Each song gets 5 keyframes + 5 LTX clips (one per abstraction level)
- [ ] Gallery HTML: rows = 0/25/50/75/100, columns = 3 songs
- [ ] Abstraction spectrum is legible within each column (literal → abstract)
- [ ] Filter vocabulary holds across all 5 levels within a song
- [ ] Identity chain OFF — we want the spectrum, not consistency (POC 14 rule)

## Method

1. Load POC 18's per-song chosen filter from its latest run dir
2. For each song:
   - Pass A once (world brief in the chosen filter, song-specific)
   - For each abstraction level (0, 25, 50, 75, 100):
     - Pass B with abstraction descriptor + first-line text + brief
     - Gemini image (no chain — independent at each level)
     - LTX I2V at 10 fps / 17 frames / 512×320
3. Write live `progress.html` during the run; `gallery.html` at the end

## Compute

- 3 songs × 5 abstraction levels = 15 LTX combos
- Per combo: ~140 s (same as POC 17 per-combo cost)
- **Expected total: ~35–40 min**

## Output

`pocs/19-abstraction-gallery/outputs/YYYYMMDD-HHMMSS/`:
- `progress.html` — live status while running
- `gallery.html` — final 5×3 grid
- `chosen_filters.json` — which filter was used per song
- `<song>/abstraction_NNN/keyframe.png`, `clip.mp4`, `prompts.json`

Reads POC 18's latest output. Abstraction descriptors are the same artist-free table validated in POC 14.
