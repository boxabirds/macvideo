# POC 28 — RESULT (v1 + v2 correction)

**Status:** v1 WEAK (crossfade only), v2 PASS (real zoom + morph)
**Date run:** 2026-04-22

## Setup

Prior POCs established two primitives:
- **POC 25:** start + end frame conditioning (PR #23) works — LTX interpolates content between the two frames
- **POC 26:** when end frame is a geometric transform of start (zoom + rotate via PIL), LTX interpolates that transform as real camera motion
- **POC 27:** the prompt text shapes the trajectory of a content morph

The question POC 28 tried to answer: **can Gemini generate an "end image" that gives LTX both a geometric zoom signal AND a content morph — producing Deforum-style zoom-through-detail scene transitions?**

## v1 — FAILED (but instructive)

**Approach:** asked Gemini for an end image "composed as if zoomed into a specific detail of the start, with that detail mid-morph". Three variants: naive, zoom-through-window, zoom-through-bird.

**Result:** all three clips were **content crossfades**, not zooms. LTX dissolved the start appearance into the end appearance; no camera push happened. User immediately called this out.

**Diagnostic:** Gemini interpreted "zoom-destination composition" as *semantic* guidance — it produced new scenes at matched framing, with subjects at similar sizes to the start. None of the end frames had the **geometric signal** (a central subject visibly larger than in the start). Without scale change between endpoints, LTX cannot infer camera motion; it only sees two images at the same framing and crossfades.

**Core principle learned:** **LTX interpolates appearance, not camera pose.** For a transition to read as camera movement, the end frame must be geometrically derived from the start (crop + upscale), not just conceptually positioned "where you'd end up".

## v2 — PASSED

**Approach:** 2-step end-image generation.
1. **PIL geometric zoom** — crop the start image around a zoom target (window / bird / narrator face), at 50% area (2× zoom), then upscale back to canvas dimensions. This image has the pixel-level geometry of "camera zoomed in 2× on target".
2. **Gemini content morph (img2img)** — feed the PIL-zoomed image as a reference + a tight prompt: "keep EXACTLY the same framing, composition, subject scale, position, and camera angle; ONLY change the kitchen content to [scene B]; preserve the charcoal style". Gemini returns an image that is geometrically a zoomed crop of A but whose content is B.

LTX then sees: start = wide scene A, end = zoomed subject with B-content. The geometric zoom (subject scale grows) produces real push-in; the morph (A→B) happens across that push.

**Variants:**
- `geo_bird` (zoom into bird region, morph kitchen→field-with-dispersing-bird)
- `geo_narrator` (zoom into narrator face, morph kitchen→field behind him)
- `geo_window` (zoom into window region, morph to open doorway onto field)

**Observed output:**
- **geo_bird (strongest):** bird grows monotonically across the 6s clip. Mid-frames show narrator receding as bird grows and starts dispersing into particles. End: bird fills right half of frame, field visible, narrator a tiny silhouette far back. Reads unmistakably as a forward dolly push on the bird while the world changes around it.
- **geo_narrator:** narrator's head scale grows across the clip. The interior ghosts out in mid-frames; hills and mist emerge behind. End: narrator fills frame, standing in field. Clean zoom-through-character.
- **geo_window:** weakest of the three — Gemini produced a half-and-half composition (kitchen wall + doorway onto field) rather than fully replacing the interior. Still shows forward motion but the zoom is less pure.

## Pass criteria

- [x] Gemini-morphed end images preserve the PIL crop's framing/scale (not recomposed)
- [x] Start-to-end shows monotonic scale increase on the zoom target (geometric zoom)
- [x] Mid-frames show continuous motion, not a crossfade
- [x] Content change (kitchen→field) happens DURING the push-in, not as a cut

## Decisions back to the pipeline

- [x] Adopt the v2 approach for scene transitions: **PIL geometric zoom → Gemini content morph** on the end keyframe
- [ ] Add a Pass D to the main pipeline: given shot N (wide) and shot N+1 (a different scene), produce shot N's end keyframe by (a) PIL-cropping shot N's start around a natural zoom target, (b) asking Gemini to morph the content into a preview of shot N+1's setting. LTX then zooms through from N to N+1 with no cut
- [ ] Pick zoom targets from the storyboard's subject_focus field; the subject is what the camera pushes toward
- [ ] Keep geo_bird-style "subject mid-transformation" prompts — they produce the richest mid-clip moments (Deforum particle dispersal)

## The generalised recipe

```
1. Take start image (wide scene A, subject at natural size)
2. Identify a zoom target inside it (what does the camera push toward?)
3. PIL: center-crop at target to 1/N area, upscale to canvas size → end_zoomed_crop
4. Gemini img2img: input end_zoomed_crop + prompt "keep exact framing, 
   only change the content to scene B" → end_morphed
5. LTX: --image start, --end-image end_morphed, prompt describes the 
   camera action ("slow forward push") + the content change
6. LTX output: continuous zoom-through with scene morphing around the 
   growing subject
```

## Lesson for future POCs

When designing an end-frame conditioning test, check whether your end frame 
has the *geometric* property you want LTX to interpret (not just the 
*semantic* property). LTX reads pixels, not intent.

## Output

`pocs/28-zoom-morph/outputs/latest/` — v1 (crossfade, reference for what doesn't work)
`pocs/28-zoom-morph/outputs/latest-v2/` — v2 (real zoom + morph, the working recipe)

Each has `index.html` with side-by-side clips + frame strips.

## Overall

**Result:** PASS (v2). The Deforum-style zoom-through-scene primitive is now a working
technique in this pipeline. v1 is retained as documentation of the failure mode.
