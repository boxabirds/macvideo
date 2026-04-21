# POC 6 — Gemini identity consistency across 5 stills

**Goal:** Generate 5 stills of the same performer across 5 different scenes, each conditioned on the previous stills as reference images. Verify the performer reads as the same person across all five, which is the entire reason we picked Gemini over Flux+IP-Adapter.

## Pass criteria

- [ ] All 5 stills return successfully from the API
- [ ] The performer in each still is recognisable as the same person
- [ ] Some wardrobe/pose variation is fine and expected — the face, build, and identifying features should be stable
- [ ] No obvious identity drift at shot 3, 4, or 5 (the harder test — later stills have more prior images to condition on)

## Inputs

- Model: `gemini-3.1-flash-image-preview`
- Performer description: `"A weathered mariner, mid-50s, grey beard, heavy grey sou'wester jacket, clear blue eyes, weather-lined face"`
- Scene prompts (scene → location/mood):
  1. Standing at the bow of a small fishing trawler, grey sea, overcast dawn
  2. Inside a dimly lit harbour pub, warm light, looking past camera
  3. On a rain-lashed cliff path, wind-whipped, distant lighthouse
  4. Below deck in the trawler's cabin, close framing, yellow lamp
  5. Walking a stone-walled village lane at dusk, slate rooftops
- Reference strategy: still 1 is unconditioned. Still 2 conditions on still 1. Still 3 conditions on stills 1+2. Still 4 conditions on 1+2+3. Still 5 conditions on 1+2+3+4.

## How to run

```bash
uv run python pocs/06-gemini-identity/scripts/run.py
```

Expects `GEMINI_API_KEY` in `.env` at repo root.

## What it generates

- `outputs/01_bow.png` through `outputs/05_lane.png`
- `outputs/meta.json` — per-still latency, token usage, prompts

## After running

Open all 5 in Preview side-by-side. In `RESULT.md` record:
- Does the performer look like the same person across all 5? Rate pair-wise similarity (1=same, 5=completely different).
- Where does identity drift start, if anywhere?
- Total cost: sum of image tokens × current pricing.
- Decision: continue with Gemini identity chaining, or revisit approach for >5-shot consistency.
