# POC 1 — LTX-2.3 smoke test on M5 Max

**Goal:** Prove `mlx-video` installs, downloads weights, and generates one short clip on this Mac. Measure wall time and peak memory. Confirm the CLI flag list matches what the main plan and guide assume.

## Pass criteria

- [ ] Clip `outputs/smoke.mp4` exists and plays in QuickLook
- [ ] Visual content roughly matches the prompt
- [ ] Wall time within 2× the guide's "6–12 min" estimate for distilled at this resolution (so ≤ ~25 min second run, first run dominated by ~19 GB weight download)
- [ ] Help output captured in `outputs/help.txt` with current flag names
- [ ] Any flag drift from `docs/20260420-music-video-ltx23-mac.md` §4 recorded in `RESULT.md`

## How to run

From repo root, first time only:

```bash
uv sync
```

Then:

```bash
bash pocs/01-ltx-smoke/scripts/run.sh
```

First run will download ~19 GB of weights to `~/.cache/huggingface/` — expect 20–60 minutes depending on connection. Subsequent runs skip the download.

## What it generates

- `outputs/smoke.mp4` — the generated clip (3 seconds, 512×320, distilled pipeline)
- `outputs/help.txt` — full `--help` output from the CLI
- `outputs/stdout.log` — full generation log
- `outputs/time.txt` — wall time + peak RSS from `/usr/bin/time -l`

## After running

Fill in `RESULT.md` with:
- Pass/fail per criterion
- Observed wall time, peak memory
- Any flag drift found
- Any surprises, errors, or workarounds needed

If POC 1 fails: project is architecturally blocked. Capture the failure mode in `RESULT.md` before deciding next steps (cloud video gen, abandon, patch mlx-video).
