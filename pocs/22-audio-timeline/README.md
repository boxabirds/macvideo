# POC 22 — Audio feature timeline per song

**Goal:** Visualise audio signals (beats, drum onsets, RMS envelope, spectral novelty, section boundaries) alongside lyric line timings for each track. Tells us at a glance which signals are clean and worth using as cut-placement candidates in POCs 23 and 24.

## What's extracted (per song)

- **Tempo + beat grid** (`librosa.beat.beat_track` on full mix)
- **Full-mix onsets** (`librosa.onset.onset_detect` on full mix — noisy but useful for comparison)
- **Drum onsets** (`librosa.onset.onset_detect` on the Demucs htdemucs_6s drums stem — cleaner)
- **RMS envelope** (loud/soft transitions)
- **Spectral novelty** (onset strength curve — textural change)
- **Section boundaries** (agglomerative clustering on chroma, synced to beats)
- **Lyric line timings** (from POC 7's `aligned.json`)

## Output

`pocs/22-audio-timeline/outputs/YYYYMMDD-HHMMSS/`:
- `<song>_timeline.png` — 4-panel multi-feature figure per song, shared time axis
- `<song>_features.json` — raw feature arrays (for POCs 23 and 24 to reuse)
- `index.html` — simple gallery of all three PNGs with basic stats

## How to run

```bash
uv run python pocs/22-audio-timeline/scripts/run.py
```

~1–2 min per song (librosa CPU work), <5 min total.

## What to look at

1. **Are drum onsets clean?** Look at panel 4 — strong spikes should match audible hits. If it's jittery/noisy, we can't rely on them for cut placement.
2. **Do section boundaries agree with what your ear hears?** The dashed red lines on panel 2. If they land on verse-to-chorus transitions → useful. If they land randomly → ditch that signal.
3. **Is the RMS envelope meaningful?** Lull → swell should show as obvious dips and rises in the green curve.
4. **Does spectral novelty catch texture changes?** Panel 3. Should spike when a new instrument enters.

Once you've eyeballed all three songs, we know which signals to feed into POC 23 (snap-to-event) and POC 24 (event-densified cuts).
