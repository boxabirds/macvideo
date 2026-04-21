# POC 13 — RESULT

**Status:** PASS

**Date run:** 2026-04-21

## What this POC validates

Integration of the core architectural primitives into one working mini-pipeline:

1. **World-first (two-pass LLM) shot planning** — Pass A reads the song once, produces a persistent character + world + style brief. Pass B generates each line's image prompt referencing that brief. Same world across shots by construction.
2. **Gemini identity chain** — shots 2+ pass prior keyframes as references; performer stays recognisably the same person across shots.
3. **Thematic filter applied consistently** — the filter word is injected into Pass A so every downstream prompt inherits it.
4. **Lyric-aligned shot timing** — each clip's video duration spans from its line's start to the NEXT line's start (gap-inclusive), so hard cuts land on lyric boundaries while one continuous audio slice plays underneath.
5. **Re-encoded concat** — libx264 + aac final mux avoids codec-mismatch stutters we hit in v1.

## Measurements (v2 run `20260421-083622-charcoal`)

| Stage | Duration |
|---|---|
| Pass A (world brief) | ~10 s |
| 3 × Pass B (line prompts) | ~15 s total |
| 3 × Gemini image (identity chain) | ~60 s total |
| 3 × LTX I2V (dev-two-stage) | 2:32 + 2:53 + 1:52 = 7:17 |
| Audio slice + concat + mux | < 5 s |
| **Total** | **~8:30** for a 9-second finished sequence |

## v1 → v2 correction log

The first run had three bugs, all architectural not cosmetic:

| Bug | Root cause | Fix |
|---|---|---|
| Audio jumps mid-sequence | Picked lines from different parts of the song (V1, V2, Ch1) and concat'd their audio slices | Contiguous lines only; **single continuous audio slice** from line 1 start to line N end |
| Video "stuttering" | `ffmpeg concat -c copy` on clips with slightly different codec params | Re-encode concat through `libx264 + aac` |
| Cuts mid-word / clipped lines | Clip duration = line's sung duration, so audio gaps between lines were discarded | Clip duration = `line[i+1].start - line[i].start` (gap-inclusive); cuts land at lyric starts, audio stays continuous |

## Identity consistency observation

The v1 and v2 runs produced visually *different* anchor characters (silver-streaked middle-aged man vs bald gaunt man) because Pass A re-ran from scratch in each run. Identity held *within* a run but not *across* reruns of prep. If the pipeline needs same-character across reruns, the character brief should be pinned after the first approved pass (or seed the LLM).

## The "build a world the song navigates" pattern

Confirmed end-to-end. The Pass A brief produced for this run:

> The narrator is a gaunt, middle-aged figure with silver-streaked hair and deeply etched facial lines, dressed in a loose-fitting, textured linen shirt that appears stiff with accumulated dust. The blackbird is a dense, shifting mass of obsidian soot that drips like viscous oil, leaving dark, smeared footprints and residue on the narrator's skin and clothes. Their world is a cavernous, sparsely furnished room with a single heavy wooden table and tall, paneled windows that filter a stark, monochromatic light. ...

Every per-line image prompt referenced this verbatim. The 3 keyframes all share the same room, same window, same table, same character, same charcoal vocabulary. The LLM even picked up "bag of noes" from the lyrics as an in-scene object and rendered a literal sack labelled **"NOES"** in keyframe 02.

## System conventions validated in this POC

- **Timestamped run dirs:** each run lands in `outputs/YYYYMMDD-HHMMSS-<tag>/`. A `latest` symlink points at the newest run.
- **`prompts.json` in every run:** captures Pass A input + output, Pass B input template + per-line inputs, per-line image prompts, per-line LTX prompts, negative prompts, audio/video concat strategies.
- **`character_brief.json`:** the Pass A output on its own, for easy re-use or pinning across runs.

## Decisions back to the main plan

- [x] Stage 4 (shot planner) architecture locked: Pass A (once per song) → Pass B (per line) → Gemini identity chain → LTX I2V → continuous audio.
- [x] Pipeline output convention: timestamped run dirs + `prompts.json` (applied to all POCs).
- [x] Gap-inclusive clip duration formula validated.
- [ ] Scale test: 40-shot whole-song version (POC 8 + 9).
- [ ] Decide: pin character brief across runs, or accept variation per fresh run.

## Overall

**PASS.** POC 13 collapses POCs 6, 7, 10, 12 into one working end-to-end flow for a 3-shot sequence. The extension to a full song is just more lines — same architecture.
