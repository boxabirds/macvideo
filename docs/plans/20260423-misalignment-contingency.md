# Audio-video misalignment contingency (2026-04-23)

## Problem

The full-song pipeline in `pocs/29-full-song/` produces clips that do **not**
stay aligned with the song audio when concatenated and muxed with the master
WAV. The blackbird shot list covers 226.0s of a 228.6s song — roughly 2.6s of
cumulative drift between video and audio over the length of the track.

Two root causes in `pocs/29-full-song/scripts/make_shots.py`:

1. **Sliver gaps between adjacent shots.** When WhisperX says line N ends at
   15.77 and line N+1 starts at 15.86, my code preserves that 90ms gap. Across
   ~60 lyric transitions in a typical song, the gaps total ~2s.
2. **LTX frame-count rounding.** LTX requires `num_frames = 1 + 8·k`. When a
   shot's target duration translates to, say, 93 frames, I was rounding to 89
   (0.133s shorter). Drift accumulates unless the concat step compensates.

The originally documented policy was *"gaps ≥ 3s become dedicated ambient
shots; shorter gaps are absorbed into the neighbouring lyric shot so coverage
is contiguous."* My implementation honoured the first half but not the second.

## What we already have (no policy change)

- Shots ≥ `MIN_GAP_FOR_AMBIENT = 3.0s` already become their own ambient shot
  (`kind: intro | gap | outro`). That remains correct.
- Intro (0 to first word) and outro (last word to song end) also already
  produce their own shot(s).

These stay as-is.

## Fix plan

**Three remedies, mutually exclusive per-clip, applied at the right layer:**

### C — Fix `make_shots.py` so the shot list is contiguous from the start

Post-pass over the shot list so that for every adjacent pair
`shots[i].end_s == shots[i+1].start_s` exactly. For each shot:

```
num_frames = ceil_to_1p8k(round((end_s − start_s) × FPS))
```

Rounding up on purpose — the rendered clip is then ≥ its audio-target span,
which lets the concat step trim to an exact duration for bit-perfect sync.

Applied to all three songs' `shots.json`. New shot lists are regenerated for
all three songs; existing rendered clips are preserved (they're keyed by shot
index; remap is already in place for the 24fps→30fps transition so the
keyframe and storyboard per shot are already set).

### A — Truncate at concat, where current clip end > target span

A handful of shot pairs have overlapping WhisperX timestamps (shots 14/15,
20/21 in blackbird — where two adjacent lyric lines share a few milliseconds
of audio). For those the rendered clip's duration is *longer* than the
contiguous-policy target.

ffmpeg filter:

```
trim=end=TARGET_DURATION_S,setpts=PTS-STARTPTS
```

Also catches every newly-rendered clip going forward — since C rounds up, all
new clips are rendered slightly long and always get trimmed by A at concat.

### B1 — Freeze last frame at concat, where current clip end < target span

The common case: an existing already-rendered clip covers less of the song
timeline than the contiguous policy now says it should. ~60 blackbird clips
are in this state, each missing 50–250ms.

ffmpeg filter:

```
tpad=stop_mode=clone:stop_duration=GAP_S
```

Viewer sees the clip's last frame held for up to ~0.25s before the next clip
starts. Below the perceptibility threshold on most lyric-line transitions.

### Why B1 over B2 (re-rendering)

LTX does not support seamless outpainting. A same-seed re-render at a larger
`num_frames` produces a *different take* — similar composition, similar
motion character, but not pixel-aligned to the existing render. To gain the
missing ~0.2s of motion per clip we would have to throw away the existing
clip and render a wholly new ~20-minute clip from scratch (at 1920×1088/30fps
dev-two-stage). Across ~60 clips that's ~20 hours of extra compute.

Decision: accept the held-last-frame hitch. Free, imperceptible, good enough
for a "first take" render. B2 remains a future option if a particular clip's
hitch is visibly jarring.

## Per-clip decision at concat time

```
for each shot i in shots.json:
    target_duration = shots[i+1].start_s - shots[i].start_s
                      (or song_duration - shots[i].start_s for the last shot)
    rendered_duration = ffprobe(clip_i)
    if   rendered_duration > target_duration + 1/60:   # A
        apply ffmpeg trim
    elif rendered_duration < target_duration - 1/60:   # B1
        apply ffmpeg tpad stop_mode=clone
    else:                                              # exact
        pass through
```

(`1/60` tolerance is one video half-frame at 30fps — below ffmpeg's PTS
precision.)

## Alignment guarantee after the fix

For any shot index `x`:
- `end_of_clip[x]` in the final concatenated video = `start_of_clip[x+1]` to
  within one video frame (33.3ms at 30fps)
- `start_of_clip[x]` in the final video = `shots[x].start_s` in the audio
  timeline — equality holds to within one video frame
- Audio resolution is much finer than one video frame, so audio-video
  alignment at each shot boundary lands on the nearest frame

Across the 228s song: **zero accumulated drift**, because every `target_duration`
sums to `(shots[N].start_s + shots[N].target_duration) − 0 = song_duration`
exactly.

## Files to touch

- `pocs/29-full-song/scripts/make_shots.py` — add contiguous post-pass; bump
  `num_frames` computation to always round up to 1+8k
- `pocs/29-full-song/scripts/render_clips.py` — concat step: per-clip
  trim-or-pad decision, concat filter graph, then mux audio
- `pocs/29-full-song/outputs/<song>/shots.json` — regenerate for all three
  songs (keyframes and storyboard remain via the existing remap)

No changes to `gen_keyframes.py`, `remap_from_24fps.py`, or the LTX render
loop itself beyond the num_frames calculation in `make_shots.py`.

## Backout

If the concat-time filter graph misbehaves, roll back to the current simple
`ffmpeg concat` demuxer + `-shortest` mux. The video will end up audio-drifted
by ~2.6s but every clip is still there and playable.
