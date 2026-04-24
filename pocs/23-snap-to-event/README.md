# POC 23 — Snap shot cuts to musical events (±100 ms)

**Goal:** Take an existing shot plan (default: POC 15's `shots.json` for my-little-blackbird) and rewrite every shot boundary to the nearest drum onset / beat / section boundary within a ±100 ms tolerance. Everything else about the plan stays the same.

## Pass criteria

- [ ] Plan modification is fast (sub-second) and preserves shot ordering and total duration
- [ ] Every snapped boundary is documented: original_t → snapped_t → event_type
- [ ] Re-rendered sequence plays in sync with the song and cuts audibly land on musical events
- [ ] Side-by-side A/B with original POC 15 sequence shows the snapped version feels more musical

## How snapping works

Priority order when picking which event to snap to (if multiple within ±100 ms):
1. **Strong drum onset** (top 75th percentile of onset strength on the drums stem)
2. **Beat** (from `librosa.beat.beat_track` on full mix)
3. **Section boundary** (from chroma-based agglomerative clustering)

If no event within ±100 ms, the boundary stays at its original position.

## Inputs

- Shot plan: `pocs/15-gap-interpolation/outputs/latest/shots.json` (default; overridable)
- Audio features: `pocs/22-audio-timeline/outputs/latest/<song>_features.json` (reuses POC 22's extraction)

## How to run

```bash
# 1. Modify plan only
uv run python pocs/23-snap-to-event/scripts/snap.py

# 2. Re-render with the snapped plan (LTX, needs MLX slot)
bash pocs/23-snap-to-event/scripts/render.sh
```

`snap.py` is instant. `render.sh` takes ~15 min on dev-two-stage for POC 15's 5-shot sequence.

## Output

`pocs/23-snap-to-event/outputs/YYYYMMDD-HHMMSS/`:
- `snapped_shots.json` — modified plan with per-boundary snap metadata
- `snap_report.md` — human-readable summary of what changed
- `final.mp4` — rendered comparison output (after `render.sh`)
- `snap_vs_original.html` — side-by-side A/B viewer
