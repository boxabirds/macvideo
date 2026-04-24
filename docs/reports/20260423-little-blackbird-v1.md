# My Little Blackbird — v1 render review (2026-04-23)

First full-length end-to-end render of a song via the pipeline in
`pocs/29-full-song/`. Target: 1920×1088 @ 30fps, abstraction 25, stained-glass
filter. 69 shots derived from WhisperX word timestamps (contiguous after the
misalignment fix earlier today).

## What worked

### Technical quality — outstanding
The per-clip image quality and motion quality are excellent. At 1920×1088 on
`dev-two-stage` the stained-glass filter holds up beautifully — the leaded
panels, the chunky brush strokes, the colour saturation, the light through
glass all read on screen. Individual clips are production-viewable.

### Timing — perfect
Scene cuts land exactly on lyric lines; ambient shots fill instrumental gaps
cleanly. With today's contiguous-coverage fix there's no audio-video drift.
The pipeline's end-to-end timing — lyric lines → shot boundaries →
clip durations → concat+mux — works as designed. No notes.

### Preview page — fantastic
Even with just the keyframes in place, the preview page at
`outputs/preview.html` was a far better way to test the video than waiting
for the full render. Being able to scrub the timeline, see shot boundaries
against audio, and read each shot's beat/camera intent made it obvious where
the narrative was and wasn't landing. **Lesson: the preview is not
scaffolding, it's a core evaluation tool. Should be built first, not last,
for every future song.**

## What needs work

### Character continuity — 70%, with imposters
About 70% of shots hold the narrator consistently. But two unrelated
characters drift in across the run:
- a bald man
- a long-haired woman

Neither appears in the world brief or matches the narrator's visual
description. They are probably drift artefacts from:
- **Identity-chain window too short:** we pass only the last 4 keyframes as
  Gemini references. Over 69 shots, early keyframes' character establishment
  is forgotten; later shots can invent new people.
- **Storyboard beats implying a second person:** Pass C occasionally writes
  beats like "the narrator looks at someone" or "a figure in the distance",
  giving Pass B and then Gemini license to generate another character.
- **Prompt B not anchoring the narrator every time:** each per-shot prompt
  only carries the subject_focus + beat; it doesn't restate the narrator's
  visual description. Gemini has to infer from references.

Fixes to consider for v2:
- Increase `IDENTITY_REF_WINDOW` from 4 to 8–12 (or keep a fixed
  "establishing keyframe" from early in the song plus the last 3 recent ones)
- Restate the narrator's visual description explicitly in the Pass B prompt
  for every shot
- Add a Pass C guardrail: "no new named characters; other figures must be
  described impersonally (a silhouette, a hand) unless the lyric demands it"

### Imagery ↔ music coherence — hit and miss
When a lyric had a concrete anchor — a window, holding the blackbird, etc. —
the image landed and the moment worked. When the lyric was abstract or
metaphorical, the image often drifted into generic visual fillers that
didn't carry the song's weight.

Root cause: Pass C beats are one-sentence summaries of what the shot should
capture, but they often default to "camera moves in on thing" rather than
"this is the emotional beat of the song at this moment". The model is
directing a storyboard, not interpreting a song.

Fixes to consider for v2:
- Feed the Pass C prompt not just the lyric line but the **surrounding
  lyric context** (the 4–6 lines bracketing it) so it understands what's
  actually being said at that moment
- Add a "metaphor → concrete image" step: for each line that's abstract,
  pick one visually anchoring object/texture/moment before writing the beat
- Possibly reduce shot count and let long instrumental spans breathe with
  continuous-motion shots, rather than cutting every 2–3s

## Key decision: iterate at 512p, promote winners to 1080p

The render took ~40 hours for one song at 1080p/30fps. That is not the right
resolution to iterate on the *creative* decisions above (character
continuity, beat-to-image mapping, etc.). The pipeline itself works; what's
left is authoring, and authoring requires many rounds.

**Action:** add a `--resolution 512` path (512×320 @ 24fps, known-fast ~3h
per song via dev-two-stage) as the default for iteration. Keep 1920×1088 for
final promotion of specific songs once the creative is locked. Accept that
512p renders are a different visual register (fewer details, different
filter reads) and evaluate them as drafts, not masters.

Concretely:
- `render_clips.py` should accept `--resolution` / `--fps` CLI flags
- Orchestrator script gets a `--draft` / `--final` mode toggle
- Preview page should be neutral to resolution (it already is)

## Numbers

- Shots: 69
- Rendered frames: ~6,781 at 30fps
- Total compute: ~40 hours at 1920×1088/30fps `dev-two-stage`
- Output: ~228s video, 1080p HEVC-less H.264
- Storage: clips/ ≈ 150 MB, final.mp4 ≈ song-length at 1080p
- Visible production flaws: character drift (2 imposters), loose lyric↔image
  coherence in ~30% of shots

## Next actions

1. Build the 512p iteration path (see above)
2. Re-render Blackbird at 512p with the v2 character-continuity + Pass C
   coherence fixes
3. Compare the two versions side-by-side in the preview page
4. Only then decide whether to commit another 40 hours to a 1080p re-render
