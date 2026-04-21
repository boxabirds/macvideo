# POC 16 — Pass C storyboard + camera arc + pathological test

**Goal:** Fix two failures from POC 15 by adding a **storyboard pass** between Pass A and Pass B:

- **Scrambled camera:** each shot's LTX motion was hardcoded and generic, so zoom direction flipped between adjacent shots.
- **No narrative flow:** Pass B saw only the current line, so adjacent shots read as local-only moments with no progression.

**Pathological test:** three identical target lines → expect three *different* progressive shots (establish → develop → culminate), not three clones.

## Architecture

```
Pass A  — WORLD BRIEF         (existing; one per song)
Pass C  — STORYBOARD          (NEW; one per sequence)
Pass B  — PER-SHOT IMAGE PROMPT  (updated; uses Pass C outputs)
LTX     — motion derived from Pass C's camera_intent  (NEW; not hardcoded)
```

## Pass C output schema

One JSON object per sequence:

```json
{
  "sequence_arc": "short description of the overall camera trajectory",
  "shots": [
    {
      "index": 1,
      "target_text": "...",
      "beat": "one concrete sentence — the narrative moment this shot captures",
      "camera_intent": "static hold | slow push in | slow pull back | pan left | pan right | tilt up | tilt down | orbit left | orbit right | handheld drift | held on detail",
      "subject_focus": "what the frame centres on",
      "prev_link": "one sentence — how this connects back to prior shot (null for first)",
      "next_link": "one sentence — how this sets up next (null for last)"
    }
  ]
}
```

## Pass criteria

- [ ] Pass C returns valid JSON with `len(shots) == len(target_lines)`
- [ ] `camera_intent` values are constrained to the vocabulary
- [ ] **Pathological test:** three identical target lines produce three distinct `beat` values with visible narrative progression
- [ ] **Pathological keyframes** are visibly different from each other (same character, same setting, different moment)
- [ ] **Camera arc coherent:** no adjacent shot pair reverses camera direction without motivation
- [ ] LTX motion follows Pass C's `camera_intent` (push in really pushes in, static really holds)

## How to run

```bash
uv run python pocs/16-storyboard/scripts/prep.py
bash   pocs/16-storyboard/scripts/run.sh
```

`TARGET_LINES` at the top of `prep.py` switches between:
- Pathological: `["He's arrived again"] * 3`
- Baseline: the verse-1 arc used in POC 15

Default is pathological (the test that matters).

## Output

`pocs/16-storyboard/outputs/YYYYMMDD-HHMMSS-<tag>/`:
- `character_brief.json` — Pass A
- `storyboard.json` — Pass C (sequence_arc + per-shot beats/camera/focus/links)
- `shots.json` — per-shot timing + image prompt + camera intent
- `keyframe_01.png` ... `keyframe_N.png` (identity-chained)
- `clip_01.mp4` ... `clip_N.mp4` (LTX I2V, motion from camera_intent)
- `final.mp4` — silent concat for visual inspection (no audio for pathological test since lines repeat)
- `prompts.json` — every prompt at every stage
