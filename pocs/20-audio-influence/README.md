# POC 20 — Audio influence on LTX-2 video generation

**Goal:** Measure how much the audio conditioning signal actually shapes the video output in the dev-two-stage pipeline. Vary two axes — audio source (full mix vs isolated drums stem) and `--audio-cfg-scale` (3, 7, 15, 20) — while holding everything else fixed (keyframe, prompt, seed, dimensions). Plus a no-audio reference.

## Pass criteria

- [ ] 9 clips per song × 3 songs = 27 clips generated
- [ ] No-audio reference is visually distinguishable from any with-audio clip
- [ ] Increasing `--audio-cfg-scale` produces progressively stronger audio-driven motion
- [ ] Drums stem produces more rhythm-aligned motion than full mix (hypothesis from early research)
- [ ] Upper-end cfg (15–20) doesn't over-cook into artefact territory

## Method

### Start times (user-specified)

| Song | Window |
|---|---|
| busy-invisible.wav | 90.0 – 115.0 s |
| chronophobia.wav | 50.0 – 75.0 s |
| my-little-blackbird.wav | 120.0 – 145.0 s |

### Shared setup per song

- **World brief (Pass A):** POC 18's chosen filter for that song (reusing existing work)
- **Keyframe prompt (Pass B):** neutral atmospheric prompt (a slow establishing moment in the song's world) — we don't want the prompt content to confound the audio comparison
- **One Gemini keyframe** generated per song, used for all 9 clips of that song
- **Fixed LTX params:** `dev-two-stage`, 512×320, 249 frames, 10 fps, seed 42, `--image-strength 1.0`, `--image-frame-idx 0`

### Axes varied

- Audio source: `none` / `full mix` / `drums stem` (htdemucs_6s output from POC 17 cache)
- `--audio-cfg-scale`: applied only when audio source is not none — values 3, 7, 15, 20

9 clips per song:
1. no audio (CFG irrelevant)
2. full mix, cfg 3
3. full mix, cfg 7
4. full mix, cfg 15
5. full mix, cfg 20
6. drums, cfg 3
7. drums, cfg 7
8. drums, cfg 15
9. drums, cfg 20

## Compute estimate

~8 min per clip × 27 = **~3.5–4.5 h**. Memory risk at 249 frames on dev-two-stage at 512×320 — first clip is the canary.

## How to run

```bash
uv run python pocs/20-audio-influence/scripts/run_all.py
```

Monitor `pocs/20-audio-influence/outputs/latest/progress.html` in a browser (auto-refresh every 15 s). Final `gallery.html` when complete.

## Output

`pocs/20-audio-influence/outputs/YYYYMMDD-HHMMSS/`:
- `progress.html` — live status
- `gallery.html` — final grid with inline video players; audio muxed in so you can hear what was driving each clip
- `<song>/shared/keyframe.png` — the shared keyframe used across all 9 variants
- `<song>/shared/full_mix.wav`, `drums.wav` — the audio slices
- `<song>/<variant>/clip.mp4` — silent LTX output
- `<song>/<variant>/clip_with_audio.mp4` — same clip muxed with the audio that conditioned it
- `<song>/<variant>/prompts.json`
