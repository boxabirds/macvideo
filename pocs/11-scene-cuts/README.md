# POC 11 — Hard cuts between unrelated shots feel cohesive

**Goal:** Generate 4 independent LTX shots (different subjects, same style base), concat with hard cuts, watch at playback speed. Tests whether the pipeline's eventual ~40-shot assembly will feel like one film or a random pile of AI clips.

This is **not** POC 4 — that tested seamless continuation (clip B from clip A's last frame). This tests the normal music-video case: unrelated shots joined by hard cuts.

## Pass criteria

- [ ] 4 clips generated, each ~3 s
- [ ] Concatenated output plays without codec/container issues
- [ ] Style cohesion holds across all 4 — same grain, same palette, same lensing feel
- [ ] Hard cuts feel deliberate, not jarring (no major colour / luminance jumps)
- [ ] Each shot is internally coherent (the original POC 2/3 quality level)

## Method

- Shared style base: `"overcast northern English light, 16mm film grain, cold palette, muted slate and ochre, cinematic wide shot"`
- 4 independent subjects:
  1. Eroded gritstone edge at dusk, slow drift, low mist
  2. Disused slate quarry, wet black rock faces, standing water at base
  3. Close macro of rain hitting dark stone, shallow focus, slow rivulets
  4. Aerial drift over peat moorland, cotton grass patches, heavy cloud
- Same pipeline (`dev-two-stage`), same seed
- T2V (no keyframe) — tests the text+style baseline cohesion, since keyframe-first would only make cohesion easier

## How to run

```bash
bash pocs/11-scene-cuts/scripts/run.sh
```

~10 min on M5 Max (4 × ~2.5 min for dev-two-stage at 512×320 / 73 frames).

## Output

- `outputs/0_edge.mp4` ... `outputs/3_moor.mp4`
- `outputs/cuts.mp4` — concatenated
- `outputs/stdout-N.log` per shot
