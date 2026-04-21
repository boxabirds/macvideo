# POC 2 — LTX-2.3 audio conditioning actually does something

**Goal:** Verify that passing `--audio-file` actually changes generated motion, and that *different* audio produces *different* motion. If audio conditioning is inert or weak, the "music drives visuals" premise fails and we plan clips on timing alone.

## Pass criteria

- [ ] Three clips generated with the same prompt and same seed, varying only the audio input
- [ ] Clip (b) "ambient" and clip (c) "beat" visibly differ in motion energy or pacing
- [ ] Both (b) and (c) differ visibly from (a) "no audio"
- [ ] Differences are significant enough to be obvious on first viewing, not just in frame-by-frame comparison

## Inputs

Same prompt, same seed, same frame count — varying only the `--audio-file` argument.

- Prompt: `"slow drift across a dark ocean surface, moonlight, 16mm grain, no figures"`
- Seed: `42`
- Frames: `121` (~5 s at 24 fps; must be `1 + 8*k`)

Audio slices (produced by the script from user's `music/` dir):
- `inputs/ambient.wav` — 5 s from `chronophobia.wav` @ 100 s (user-confirmed most ambient)
- `inputs/beat.wav` — 5 s from `busy-invisible.wav` @ 100 s (user-confirmed most rhythmic)

## How to run

```bash
bash pocs/02-ltx-audio-cond/scripts/run.sh
```

Three sequential generations, each ~30–60 s on M5 Max at 512×320 (per POC 1 timings, scaled for 121 frames vs 73). Total expected wall time: ~2–3 min.

## What it generates

- `outputs/a_no_audio.mp4` — control
- `outputs/b_ambient.mp4` — conditioned on the ambient slice
- `outputs/c_beat.mp4` — conditioned on the beat slice
- `outputs/stdout-{a,b,c}.log` — per-run logs

## After running

Play all three in QuickLook side-by-side. Fill in `RESULT.md` with:
- Does (b) differ from (c) visibly in motion energy, speed, direction, complexity?
- Does audio conditioning produce a meaningful signal, a weak one, or nothing?
- If weak/nothing: do we drop `--audio-file` from the pipeline architecture?
