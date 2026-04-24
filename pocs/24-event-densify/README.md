# POC 24 — Densify long shots with cuts at strong drum onsets

**Goal:** When a shot in the plan is long enough that it goes visually stale (e.g. POC 15's gap shots that fill 2+ seconds of instrumental), split it at strong drum onsets inside that window so the viewer gets a rhythmic punch instead of a held static moment.

## Pass criteria

- [ ] Shots longer than `MIN_LONG_S` (default 2.0 s) get candidate split points
- [ ] Split points are drum onsets in the top-75th-percentile of onset strength, within the shot window
- [ ] Split shots reuse the parent shot's prompt + keyframe (same image, just shorter clip)
- [ ] Resulting plan preserves total duration and shot ordering
- [ ] Re-rendered sequence has visibly more rhythmic cutting than POC 15's original

## How densification works

1. For each shot in the input plan, find strong drum onsets that fall strictly inside `(start_t, end_t)` with at least `MIN_SPLIT_GAP` from either endpoint (default 400 ms — avoid hairline cuts).
2. If ≥ 1 qualifying onset exists and the shot is ≥ `MIN_LONG_S`, split at the onsets.
3. Each child shot inherits the parent's `image_prompt` and `keyframe_file` (same visual, just re-generated at a shorter duration so LTX motion resolves cleanly within it).
4. Cap at `MAX_SPLITS_PER_SHOT` (default 3) so no one shot gets over-sliced.

Short shots, shots with no strong drum onsets, and shots whose internal onsets are all too close to the edges pass through untouched.

## Inputs

- Shot plan: `pocs/15-gap-interpolation/outputs/latest/shots.json` (default; overridable)
- Audio features: `pocs/22-audio-timeline/outputs/latest/<song>_features.json`

## How to run

```bash
# 1. Densify only
uv run python pocs/24-event-densify/scripts/densify.py

# 2. Re-render with the densified plan (LTX)
bash pocs/24-event-densify/scripts/render.sh
```

`densify.py` is instant. `render.sh` takes LTX compute proportional to the number of new shots added (typically 2–5 extra short shots).

## Output

`pocs/24-event-densify/outputs/YYYYMMDD-HHMMSS/`:
- `densified_shots.json` — expanded plan
- `densify_report.md` — what got split and why
- `final.mp4` — rendered output (after `render.sh`)
- `densify_vs_original.html` — side-by-side A/B

Note: densified plans typically pair well with snap-to-event (POC 23). The two compose — snap first, then densify, or vice versa. If you want to test the composition, modify `snap.py` or `densify.py` to read from each other's output.
