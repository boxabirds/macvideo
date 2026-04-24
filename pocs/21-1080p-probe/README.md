# POC 21 — 1920×1080 / 30 fps max-frames probe

**Goal:** Find the maximum `num_frames` that fits in memory for LTX-2 `dev-two-stage` at 1920×1080 / 30 fps. Determines the per-shot duration ceiling for production pipeline at final resolution.

## Method

Probe increasing frame counts until OOM / non-zero exit / missing output:

- `num_frames` candidates (each satisfies `1 + 8k`): **9, 17, 25, 33, 49, 73, 97, 121, 145, 193, 241**
- At 30 fps these are 0.30 s, 0.57 s, 0.83 s, 1.10 s, 1.63 s, 2.43 s, 3.23 s, 4.03 s, 4.83 s, 6.43 s, 8.03 s
- Resolution: 1920×1080
- Pipeline: `dev-two-stage` (same memory profile as `dev-two-stage-hq`, faster sampler — probing limits not quality)
- I2V from a single generated keyframe so we match production's code path (VAE encoder active)
- Single-frame keyframe generated once via Gemini at run start

Two passes:
1. **Default tiling** (`--tiling auto`) — baseline
2. **Aggressive tiling** (`--tiling aggressive`) — memory-saving mode; should push the ceiling up

Stop each pass on first failure; log peak memory and wall time for every attempt.

## Output

`pocs/21-1080p-probe/outputs/YYYYMMDD-HHMMSS/`:
- `progress.html` — live table of results (auto-refresh 15 s)
- `results.json` — machine-readable per-attempt data
- `shared/keyframe.png` — the Gemini-generated keyframe used for all I2V runs
- `attempts/<tiling>_<num_frames>/clip.mp4` — generated clip if successful
- `attempts/<tiling>_<num_frames>/ltx.log` — full LTX stdout
- `attempts/<tiling>_<num_frames>/time.txt` — `/usr/bin/time -l` output (OS-side peak RSS)

## What we learn

- Hard upper bound on single-clip duration at 1080p/30fps
- Whether `--tiling aggressive` buys meaningful extra frames
- Wall-time-per-frame scaling curve at 1080p
- Whether we need a smaller production resolution (1280×720 fallback?) or a shot-planning rule that keeps individual shots under X seconds

## How to run

```bash
uv run python pocs/21-1080p-probe/scripts/run.py
```

Total wall time highly uncertain — depends on where OOM hits. Probably 30–90 min per pass. Run in background; watch `progress.html`.
