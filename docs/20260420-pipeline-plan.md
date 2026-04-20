# Automatic music → music-video pipeline

**Author context:** user has 3–4 min WAVs with vocals, wants dramatic and sparkling output, not ambient. Deep prior experience with Deforum (~2023). Proven tricks to port forward:

- Whisper word-level lyric transcription with accurate timings
- LLM per-line prompting using whole-song context
- LLM-picked style from a curated list (papercut, watercolour, steampunk, etc.)
- Interest in partial singing lip-sync (hero shots, not every shot)

## Brutal framing

The LTX-2.3 guide already in `docs/` is aimed at ambient-instrumental / no-figures / no-text. That's the wrong target for what you're actually asking for. It's reusable as the clip-generation engine but **not** as the whole pipeline. You need a layer above it that is lyric-aware and song-structure-aware. The LTX-2.3 guide is the renderer; the real work is the director.

Three things that won't port cleanly and you should stop hoping will:

1. **Deforum-style frame-by-frame warping / latent walks.** That aesthetic is tied to SD1.5-era latent interpolation. LTX-2.3 and peers generate coherent clips, not drifting frames. You'll get prettier shots, less of that "hallucinating through a tunnel" look. Good trade, but it *is* a trade.
2. **Single-model "full music video" generators.** Nothing end-to-end on a Mac produces a 3-minute coherent music video in one shot. Pipeline or nothing.
3. **Lip-sync on Mac to production quality.** The best performers (Wan 2.2 S2V, Hedra, Sync.so) are CUDA-first or cloud-only. Expect either a 4090 box, cloud spend, or visibly second-tier results for sung lip-sync on Mac. Don't self-deceive on this.

## Pipeline shape

```
track.wav
  │
  ├─► [1] Normalise + stem-separate (Demucs htdemucs_6s)
  │     → stems/{vocals,drums,bass,other}.wav
  │
  ├─► [2] Lyric transcription (WhisperX or whisper-timestamped)
  │     → lyrics.json with word-level timings
  │
  ├─► [3] Structure analysis (librosa + LLM pass over lyrics)
  │     → sections.json: verse/chorus/bridge, bar/beat grid
  │
  ├─► [4] Shot plan generation (LLM, song-aware)
  │     → shotplan.yaml: list of shots, each with:
  │         - start_t, end_t (seconds)
  │         - triggering lyric line(s) or instrumental section
  │         - prompt (subject, light, texture, colour)
  │         - style (papercut / watercolour / steampunk / ...)
  │         - lip_sync: bool  (hero shot, trigger S2V pipeline)
  │         - audio_slice (path + window of source/stem)
  │
  ├─► [5] Clip generation
  │     ├─ default shots → LTX-2.3 distilled (iteration) / dev-hq (final)
  │     └─ lip-sync shots → separate S2V pipeline (see tradeoffs)
  │
  ├─► [6] Timeline assembly (ffmpeg, deterministic cuts on word boundaries)
  │     → rough_cut.mp4 (the whole track, auto-assembled)
  │
  └─► [7] Human polish in NLE (optional, but better than purely auto)
        → final.mp4
```

## Stage-by-stage

### 1. Audio prep

Existing section 6 of the LTX-2.3 guide covers this. Use `htdemucs_6s` now that the guide has been updated. Keep vocals stem separate — you need it for transcription *and* for lip-sync audio source.

### 2. Lyric transcription

Use **WhisperX** (`m-bain/whisperX`, active as of 2026) on the isolated vocals stem, not the full mix. WhisperX does forced alignment with wav2vec2 which gives word-level timings good enough to cut on. Fallback is `whisper-timestamped`.

Output schema — keep it flat:

```json
{"words": [{"word": "river", "start": 12.34, "end": 12.61, "line_id": 3}, ...],
 "lines": [{"line_id": 3, "text": "down the river in the rain", "start": 12.20, "end": 13.80}, ...]}
```

Mac inference on an M5 Max for a 4-minute vocal stem: well under a minute with `large-v3` quantised.

**Non-obvious gotcha:** if the track is heavily processed vocals (vocoded, auto-tuned, heavily reverbed), transcription accuracy craters. Budget time for manual correction of 5–15% of words, because **bad lyrics → bad prompts** and you can't recover downstream.

### 3. Structure analysis

Two passes:

- `librosa.beat.beat_track` + `librosa.segment` for bars, beats, section boundaries from audio alone.
- LLM pass: give it the full lyrics with timings and ask it to label sections (`intro`, `verse`, `pre-chorus`, `chorus`, `bridge`, `solo`, `outro`) and to flag "big moments" (drop, last chorus, key change). Ground the LLM's section labels against librosa's boundaries; disagreements flag for review.

Cache this output. You'll iterate on prompts a lot; you don't want to re-run Whisper every time.

### 4. Shot plan generation (this is where your old tricks shine)

This is the director step. One LLM call, whole song as context, structured output.

Port your old "in the context of this song, generate an image prompt best representing this one line" trick **verbatim** into the system prompt. It was good then, it's better now with Claude Opus 4.7 handling the context.

System-prompt sketch:

```
You are a music video director. Given a full song's lyrics with timings and a
section map, produce a shot plan as a JSON list. For each shot:

- Decide duration. Default: one lyric line = one shot. But sometimes a single
  word or a held note deserves its own shot, and sometimes a whole pre-chorus
  is one slow push — use musical judgement.
- Write a prompt in the aesthetic style chosen for this song (see below).
  Anchor each prompt on: subject, light, texture, colour. One subject per shot.
- Decide if the shot is lip_sync-eligible (vocals present, visible performer
  would land the moment). Default false. Mark no more than ~15% of shots true.
- For instrumental sections, make the shots abstract or landscape;
  for lyric-present sections, let the lyric drive the image.

Return JSON matching the schema below. No prose.
```

Style selection: keep your curated list, add a second LLM pass that picks 1–2 styles appropriate to the song's mood and era, then applies them to every prompt as a suffix. Don't let the LLM pick a fresh style per shot — the video will look schizophrenic.

**"Dramatic and sparkling":** build that into the style-base phrase. E.g. `high contrast, volumetric light, rim lighting, bokeh highlights, particulate sparkle, anamorphic lens flares, shallow depth of field, saturated accent colour against desaturated ground`. Calibrate by generating 3–4 test shots before running a full batch.

### 5. Clip generation

**Default path** — LTX-2.3 via the existing guide's script. Two changes to that script to adapt it for this pipeline:

- Input is now `shotplan.yaml`, not the ambient-oriented `prompts/<track>.yaml`.
- Each shot has a bespoke duration (seconds), not a fixed 10 s slice. Compute `--num-frames` per shot from `(end_t - start_t) * fps`.
- `--audio-file` per shot is a windowed slice of the vocal stem (for lip-adjacent shots) or the full mix (for wide shots).

**Lip-sync path** — this is a separate sub-pipeline that runs *only* on shots marked `lip_sync: true`. Honest options for Apple Silicon today:

| Option | Quality | Mac-native? | Cost | Notes |
|---|---|---|---|---|
| **Hedra Character-2 / Sync.so (cloud)** | Best | Cloud, any OS | Per-second pricing | Upload audio + reference image, download lip-synced video. Expensive if you use it for >20% of shots; fine for hero moments. |
| **SadTalker (local)** | Okay for talking, shaky for singing | Runs on Mac via PyTorch/MPS | Free | Older, but still the most Mac-friendly local option. Singing performance is weaker than speech. |
| **LatentSync (local)** | Better than SadTalker | PyTorch, MPS-capable | Free | Newer, more finicky to set up, but generally a step up in quality. |
| **Wan 2.2 S2V (CUDA)** | Strong | No — CUDA/4090 class | Free (if you own one) | The guide's troubleshooting section already rules this out on Mac. If you have a 4090 box, offload just the lip-sync shots. |

My recommendation: **cloud lip-sync (Hedra) for hero shots only, capped at ~10–15% of the shots in the video.** Cost stays contained, quality lands where the audience is looking closest. Don't try to do every vocal line — it dilutes the drama and burns money.

Reference images for lip-sync: generate or supply a still for each performer identity. Keep identities consistent across a video (same still for all "Singer A" shots) or the audience will read it as deliberate stylistic fragmentation, which is a choice, but probably not the one you want.

### 6. Timeline assembly

`ffmpeg` with a concat demuxer, stitched on the timings from the shot plan. The whole point of planning on word boundaries is that the rough cut is usable — not broadcast-ready, but not a meaningless pile of clips either. Output at the song's native resolution with the original master WAV on the audio track.

Build this as `scripts/assemble.py`. Deterministic. No model calls. ffmpeg only.

### 7. Human polish

Leave this for the NLE. This is the same principle as §11 of the LTX guide — don't grade in the model, don't cut in the model. The rough cut lets you evaluate whether the *plan* worked before investing further.

## What I'd build first

Don't scaffold all seven stages before running anything. Order:

1. **Stage 2 + 4 (transcription + shot plan) on one track, no generation.** Just produce the YAML. Eyeball it. Is the LLM making the shot choices you'd make? If the plan is bad, fixing it here is free; fixing it after you've generated 60 clips is not.
2. **Stage 5 default path**, 5 shots, distilled LTX-2.3. Measure real wall-time on your hardware. The guide's numbers are guesses.
3. **Stage 6 assembly** with those 5 shots dropped into the full track's timeline. Watch it. Decide if the shot-plan resolution matches the music.
4. **Expand to full track on distilled.** Iterate prompts and style base.
5. **Pick the 2–3 hero shots. Try Hedra on just those.** Decide if lip-sync is worth it before scaling.
6. **HQ pass on approved shot plan.** Overnight.
7. **NLE polish.** Not automatable. Don't try.

## What to push back on in your own plan

- **"Automatically" is doing work here.** A fully automatic pipeline produces a watchable rough cut. It does *not* produce a finished music video you'd release. If your mental model is "press button, get video," calibrate that expectation now — three rounds of prompt iteration + one NLE pass is still dramatically less work than Deforum was, but it's not zero.
- **Style consistency vs. variety.** Your old Deforum work had a signature look partly because SD1.5 *forced* consistency through its limitations. Modern models will happily give you 40 different aesthetics across one song. You'll need to actively *constrain* the style, not expand it.
- **Lip-sync temptation.** It's the flashiest capability and it will be the biggest quality/cost trap. Keep the cap at 15% of shots and only on moments that actually reward the viewer looking closely.

## Open questions for you before I build anything

1. **Target output resolution.** 720p for the iteration pass is fine; is final 1080p acceptable or do you want 4K? 4K multiplies costs meaningfully on the HQ path.
2. **Reference imagery for performers.** Do you want LLM-generated stills, or will you supply reference photos for any lip-sync shots? This changes the identity-consistency approach.
3. **Budget ceiling for cloud lip-sync per track.** Setting a number now prevents the 15% cap from drifting to 40%.
4. **Does "dramatic and sparkling" actually mean one style, or a family?** If a family, list the bounds. "Dramatic" can mean noir, epic-cinematic, high-contrast-expressionist, or gothic — all different prompt bases.
