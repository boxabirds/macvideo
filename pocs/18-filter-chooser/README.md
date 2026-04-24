# POC 18 — LLM filter chooser (Pass 0)

**Goal:** For each song in `music/`, have `gemini-3-flash-preview` read the full lyrics + the accepted-filter palette and pick the best-fitting filter, with a rationale and runners-up. Gemini-only — no local compute. Safe to run in parallel with any LTX work.

## Pass criteria

- [ ] For each song, a `chosen_filter` is returned and it exists in the accepted list
- [ ] Rationale names specific features of the song (imagery / mood / metaphor) that justify the choice, not vague descriptors
- [ ] Runners-up are ranked with one-line reasons
- [ ] All three songs get their own choices (not all identical)

## How to run

```bash
uv run python pocs/18-filter-chooser/scripts/run.py
```

~30 s per song (one LLM call each). Total ~2 min for 3 songs.

## Output

`pocs/18-filter-chooser/outputs/YYYYMMDD-HHMMSS/`:
- `<song>.json` — `{chosen_filter, rationale, runners_up[]}`
- `report.html` — all three songs side-by-side with rationales, links back to POC 17's gallery cells for visual reference
- `prompts.json` — prompt templates used

## Notes

- Only filters with `status: accepted` are offered; rejected ones are hidden from the LLM.
- `report.html` links each song's chosen filter to its POC 17 gallery cell (`../../17-filter-gallery/outputs/latest/<song>/<filter>/keyframe.png`) so you can see the actual rendered keyframe for the choice.
