# POC 5 — Gemini `gemini-3.1-flash-image-preview` single still

**Goal:** Prove API access, auth, and prompt adherence for a single still via Google's Nano Banana 2 model. Confirm the preview model ID still resolves and capture baseline cost/latency.

## Pass criteria

- [ ] API call returns an image without auth errors
- [ ] Image quality is adequate for use as an LTX-2.3 seed frame (i.e. not an API error-placeholder, not tiny, recognisable content)
- [ ] Prompt adherence — the image plausibly represents the prompt
- [ ] Latency and cost recorded for baseline planning

## Inputs

- Model: `gemini-3.1-flash-image-preview`
- Prompt: one expanded style from our configured set (steampunk) — tests whether the LLM-expanded prompt approach the pipeline will use is producing usable stills.

## How to run

```bash
uv run python pocs/05-gemini-still/scripts/run.py
```

Reads `GEMINI_API_KEY` from `.env` (repo root).

## What it generates

- `outputs/still.png` — the image
- `outputs/meta.json` — model ID, latency, prompt, response metadata

## After running

Open `still.png`. In `RESULT.md` record:
- Does it match the prompt?
- Resolution / aspect ratio returned
- Latency (first call)
- Any API warnings or rate-limit indicators

If the model ID 404s: try successors (`gemini-2.5-flash-image`, whatever the current "Nano Banana N" is) and update the locked decisions in the main plan.
