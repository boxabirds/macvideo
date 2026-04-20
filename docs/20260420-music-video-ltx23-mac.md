# Music Video Generation with LTX-2.3 on Apple Silicon

## An implementation guide for agent execution

**Target hardware:** MacBook Pro M5 Max, 128GB unified memory
**Model:** Lightricks LTX-2.3 via MLX (Prince Canuma's `mlx-video`)
**Output:** A library of short AI-generated video clips, audio-conditioned on sections of a finished track, for hand-assembly into a finished music video in DaVinci Resolve or Premiere.

---

## 0. Agent instructions

You are executing this guide on behalf of a technical user (music producer, background in software). Run commands in sequence. At each `VERIFY` checkpoint, confirm the expected state before continuing. If a step fails in a non-obvious way, stop and ask. Do not prompt the user for decisions that are already specified in this guide. Do not add narration or commentary the user did not request.

Assume the user is doing other work on the machine while generation runs overnight; do not open GUI applications or grab focus.

---

## 1. Aesthetic reference

The music is ambient/electronic in the lineage of **Craven Faults** (industrial-pastoral, eroded northern English landscapes, overcast light, 16mm grain, no figures) and **Biosphere** (arctic minimalism, glacial, spatial, slow motion).

Default aesthetic rules for all prompts unless the user overrides:

- No people, faces, or performers
- No text, logos, or captions
- Muted palette — greys, ochres, slate, bone, moss, peat
- Overcast or dusk light, never midday sun
- Slow motion, slow camera moves — no whip pans, no quick cuts
- Natural textures — stone, water, vegetation, mist, dust, erosion
- Grain and imperfection preferred over clean digital look

If the user requests prompts that break these defaults, follow them — but surface the conflict once so they can confirm.

---

## 2. Prerequisites

Run the following and fix any missing pieces before continuing:

```bash
sw_vers                    # macOS 14 Sonoma or later
uname -m                   # arm64
df -h ~                    # at least 100 GB free
```

Install Homebrew if missing:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Install system tools:

```bash
brew install ffmpeg git
```

Install `uv` (Python environment manager — faster and saner than pip/venv):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
```

**VERIFY:** `uv --version` prints a version number.

---

## 3. Project structure

```bash
export PROJECT_ROOT="$HOME/music-videos"
mkdir -p "$PROJECT_ROOT"/{tracks,stems,sections,prompts,clips,clips-hq,logs,scripts}
cd "$PROJECT_ROOT"
```

| Directory   | Purpose                                                      |
|-------------|--------------------------------------------------------------|
| `tracks/`   | Source WAVs (user-supplied)                                  |
| `stems/`    | Demucs-separated stems, or Logic-exported stems              |
| `sections/` | Audio slices per track, ~10 s each, used for conditioning    |
| `prompts/`  | One YAML per track: section-by-section prompt definitions    |
| `clips/`    | Generated clips, iteration quality (distilled pipeline)      |
| `clips-hq/` | Generated clips, final quality (dev-two-stage-hq pipeline)   |
| `logs/`     | Per-clip generation logs                                     |
| `scripts/`  | Helper scripts defined below                                 |

---

## 4. Install `mlx-video` and supporting packages

```bash
cd "$PROJECT_ROOT"
uv venv
source .venv/bin/activate

# Pin mlx-video to a known commit. main drifts weekly; an unpinned install
# on an arbitrary day will eventually break this guide. Resolve the current
# HEAD once and record it here before running a batch:
#   git ls-remote https://github.com/Blaizzy/mlx-video.git HEAD
export MLX_VIDEO_SHA="<paste-resolved-sha>"
uv pip install "git+https://github.com/Blaizzy/mlx-video.git@${MLX_VIDEO_SHA}"
uv pip install demucs soundfile pyyaml
```

**VERIFY:**

```bash
python -c "import mlx_video; print(mlx_video.__file__)"
uv run mlx_video.ltx_2.generate --help | head -40
```

First command prints a path, no `ImportError`. Second command prints the CLI's flag list. **Read this help output and confirm the flags used in section 7 below still match the installed version.** If flag names have drifted (`--audio-file`, `--pipeline`, `--model-repo`, `--cfg-scale`, `--output`, `--num-frames`, `--fps`, `--width`, `--height`), update the generation script accordingly before running a batch. As of this guide's authoring the output flag is `--output` / `-o`; earlier docs may show `--output-path` — trust the `--help` output over this guide.

---

## 5. Smoke test: download weights and generate one 3-second clip

LTX-2.3 weights are pulled from Hugging Face on first use and cached under `~/.cache/huggingface/`. The distilled variant is ~19 GB; the dev variant is ~42 GB.

```bash
uv run mlx_video.ltx_2.generate \
  --prompt "grey mist over peat bog, cold palette, overcast light, 16mm grain, no figures" \
  --pipeline distilled \
  --model-repo prince-canuma/LTX-2.3-distilled \
  --width 512 --height 320 \
  --num-frames 72 --fps 24 \
  --output "$PROJECT_ROOT/clips/_smoke.mp4"
```

First run may take 20–60 minutes (download dominates). Subsequent distilled generations at this resolution take ~3–8 minutes on M5 Max.

**VERIFY:** `clips/_smoke.mp4` exists and plays. If the repo name `prince-canuma/LTX-2.3-distilled` 404s, check `https://huggingface.co/prince-canuma` for the current name — the ecosystem shifts quickly.

If this step fails, **stop and fix**. Do not proceed to batch generation until a single clip generates cleanly end-to-end.

---

## 6. Audio preparation

For each track in `tracks/`:

### 6a. Normalise format

```bash
ffmpeg -i tracks/<name>.<ext> -ar 48000 -ac 2 -sample_fmt s16 tracks/<name>.wav
```

(Skip if already WAV at 48 kHz stereo.)

### 6b. Stem separation (recommended for ambient content)

LTX-2.3 is a joint audio-visual DiT with a causal audio VAE over 16 kHz mel-spectrograms — not a shallow feature-hook onto the video model. Audio and video are coupled streams during generation. In practice a cleaner source with dominant texture still conditions better than a busy full mix: for ambient electronic, the pad/drone layer tends to drive mood most usefully; for rhythm-forward tracks, percussion can be better. (Confirm from `--help` whether `--audio-file` supplies reference audio to the audio branch or replaces joint audio generation — the model can do either depending on the pipeline variant.)

```bash
demucs --two-stems=bass tracks/<name>.wav -o stems/
# produces stems/htdemucs/<name>/bass.wav and stems/htdemucs/<name>/no_bass.wav
```

Or for the "everything except vocals" case:

```bash
demucs --two-stems=vocals tracks/<name>.wav -o stems/
```

For a richer split (pads isolated from drums, bass, other), use the 6-stem model:

```bash
demucs -n htdemucs_6s tracks/<name>.wav -o stems/
# produces drums/bass/vocals/piano/guitar/other stems
```

This is often the better choice for ambient/electronic work where "pad" or "other" is what you actually want driving mood.

If the user has Logic-exported stems directly, copy them into `stems/<name>/` and skip Demucs.

**Ask the user** (once per track) which source should drive audio conditioning: the full mix, a specific stem, or test several. Default to the lowest-frequency-dominant stem for ambient, full mix for anything rhythmic.

### 6c. Section slicing

Write `scripts/slice_audio.sh`:

```bash
#!/usr/bin/env bash
# Usage: slice_audio.sh <input.wav> <seconds_per_slice> <output_dir>
set -euo pipefail
input="$1"; slice_len="$2"; out_dir="$3"
mkdir -p "$out_dir"
duration=$(ffprobe -i "$input" -show_entries format=duration -v quiet -of csv="p=0")
i=0; start=0
while awk "BEGIN {exit !($start < $duration)}"; do
  printf -v fname "%03d.wav" $i
  ffmpeg -y -hide_banner -loglevel error \
    -ss "$start" -i "$input" -t "$slice_len" \
    -c:a pcm_s16le -ar 48000 "$out_dir/$fname"
  i=$((i+1))
  start=$(awk "BEGIN {print $start + $slice_len}")
done
echo "Created $i slices in $out_dir"
```

```bash
chmod +x scripts/slice_audio.sh
```

Run it per track, 10-second slices:

```bash
scripts/slice_audio.sh stems/htdemucs/<name>/no_vocals.wav 10 sections/<name>/
```

For a 3-minute track this produces ~18 slices: `000.wav` through `017.wav`.

---

## 7. Prompt authoring

One YAML file per track at `prompts/<name>.yaml`:

```yaml
track: "track01"
audio_source: "stems/htdemucs/track01/no_vocals.wav"

# Appended to every section prompt. Houses the aesthetic defaults.
style_base: >
  ambient, cinematic, overcast northern light, 16mm grain, no figures,
  no text, muted palette of slate grey, ochre, moss, peat

sections:
  - id: 0
    audio: "sections/track01/000.wav"
    prompt: "aerial drift over eroded peat moorland, patches of cotton grass, low mist rolling between hills"

  - id: 1
    audio: "sections/track01/001.wav"
    prompt: "slow push into a disused slate quarry, wet black rock faces, standing water at the base"

  - id: 2
    audio: "sections/track01/002.wav"
    prompt: "close macro of rain hitting dark stone, shallow focus, slow rivulets tracing lichen"

  # ... one entry per audio slice. Vary subject, hold the atmosphere constant.
```

If the user has not supplied prompts, **generate a starter YAML** of 15–20 sections in the default aesthetic and present it to them for review before running any batch. Offer one set; don't ask them to choose between variants unless they ask.

Good prompting heuristics for this aesthetic:

- **One subject per shot.** "Eroded gritstone edge at dusk" — not "eroded gritstone edge and a ruined mill and crows."
- **Name the texture, name the light, name the colour.** Those three anchors do more work than adjectives.
- **Avoid verbs of rapid motion.** "Drift," "push," "pan slowly," "hold," "breathe." Never "fly," "race," "zoom."
- **Include `no figures, no text`** unless the user explicitly wants them. The model otherwise drifts toward inserting people.

---

## 8. Batch generation script

Write `scripts/generate.py`:

```python
#!/usr/bin/env python
"""Batch-generate LTX-2.3 clips from a prompt YAML."""
import argparse
import pathlib
import subprocess
import sys
import time
import yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt_file", type=pathlib.Path)
    ap.add_argument("--pipeline", default="distilled",
                    choices=["distilled", "dev", "dev-two-stage", "dev-two-stage-hq"])
    ap.add_argument("--model-repo", default="prince-canuma/LTX-2.3-distilled")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--cfg-scale", type=float, default=3.0)
    ap.add_argument("--fps", type=int, default=24)
    # Default num-frames matches the 10 s audio slice length from section 6c.
    # Override if slice length changes, or let the model pick by omitting.
    ap.add_argument("--num-frames", type=int, default=240)
    ap.add_argument("--clips-dir", type=pathlib.Path, default=pathlib.Path("clips"))
    ap.add_argument("--logs-dir", type=pathlib.Path, default=pathlib.Path("logs"))
    ap.add_argument("--skip-existing", action="store_true", default=True)
    args = ap.parse_args()

    spec = yaml.safe_load(args.prompt_file.read_text())
    track = spec["track"]
    style_base = spec.get("style_base", "").strip()

    out_dir = args.clips_dir / track
    log_dir = args.logs_dir / track
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    total = len(spec["sections"])
    t_batch = time.time()

    for i, section in enumerate(spec["sections"], start=1):
        sid = int(section["id"])
        out_path = out_dir / f"{sid:03d}.mp4"
        log_path = log_dir / f"{sid:03d}.log"

        if args.skip_existing and out_path.exists():
            print(f"[{i:02d}/{total}] skip  {out_path}")
            continue

        prompt = section["prompt"].rstrip(". ")
        full_prompt = f"{prompt}. {style_base}" if style_base else prompt

        cmd = [
            "uv", "run", "mlx_video.ltx_2.generate",
            "--prompt", full_prompt,
            "--audio-file", section["audio"],
            "--pipeline", args.pipeline,
            "--model-repo", args.model_repo,
            "--width", str(args.width),
            "--height", str(args.height),
            "--num-frames", str(args.num_frames),
            "--fps", str(args.fps),
            "--cfg-scale", str(args.cfg_scale),
            "--output", str(out_path),
        ]

        print(f"[{i:02d}/{total}] run   {out_path.name}: {prompt[:60]}...")
        t0 = time.time()
        with log_path.open("w") as logf:
            logf.write(f"CMD: {' '.join(cmd)}\n\n")
            result = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT)
        dt = (time.time() - t0) / 60.0

        if result.returncode != 0:
            print(f"[{i:02d}/{total}] FAIL  {out_path.name} ({dt:.1f} min, see {log_path})")
        else:
            print(f"[{i:02d}/{total}] done  {out_path.name} ({dt:.1f} min)")

    total_dt = (time.time() - t_batch) / 60.0
    print(f"\nBatch complete in {total_dt:.1f} min.")


if __name__ == "__main__":
    sys.exit(main())
```

---

## 9. Run

### Iteration pass (fast, for choosing compositions)

```bash
source .venv/bin/activate
python scripts/generate.py prompts/track01.yaml --pipeline distilled
```

Expect ~15–25 minutes per clip at 1280×720 on M5 Max. For an 18-section track, batch total ~5–7 hours. Skippable with `Ctrl-C` at any clip boundary; re-running resumes where it stopped thanks to `--skip-existing`.

### Final pass (quality, overnight)

```bash
caffeinate -disu python scripts/generate.py prompts/track01.yaml \
  --pipeline dev-two-stage-hq \
  --model-repo prince-canuma/LTX-2.3-dev \
  --clips-dir clips-hq
```

Expect ~45–90 minutes per clip. Batch total ~14–27 hours for an 18-section track — start before sleep, check in morning, let it finish through the day if needed. `caffeinate -disu` prevents sleep/display off but keeps the laptop usable if opened.

For maximum throughput overnight, before running:

- Quit Logic, Chrome, Slack, Zoom
- Plug in, cool surface, don't leave the laptop on a bed or cushion
- `sudo pmset -c disablesleep 1` if you really want belt-and-braces (AC-only scope; remember to re-enable: `sudo pmset -c disablesleep 0`). Do not use `-a` — that applies to battery too and will drain the laptop if it gets unplugged overnight.

---

## 10. Review and iterate

After the iteration pass:

```bash
open clips/track01/
```

Scrub through clips in QuickLook (spacebar). For each unsatisfactory clip:

1. Edit that section's prompt in `prompts/track01.yaml`.
2. Delete the clip: `rm clips/track01/NNN.mp4`
3. Re-run the generate script; `--skip-existing` handles the rest.

Only move to the HQ pass once the iteration pass is approved by the user.

---

## 11. Final assembly — user-driven, not agent

Clip generation is the agent's job; editing a finished video is not. At the end of the HQ pass, surface this to the user:

> Clip generation complete. Final assembly is a creative step best done in a proper NLE. Open DaVinci Resolve (free) or Premiere. Import `clips-hq/track01/` and the original master from `tracks/track01.wav`, drop the master on the audio track, lay clips onto the video track in order, crossfade or hard-cut between them at musical boundaries, add grain/grade passes in the NLE. Don't colour-grade in the model — grade in the NLE where you can see it against the whole piece.

---

## 12. Troubleshooting

**`ImportError: No module named mlx_video`** — venv not activated. `source .venv/bin/activate`.

**Flags differ from what this guide shows** — `mlx-video` evolves quickly. Run `uv run mlx_video.ltx_2.generate --help` and reconcile flag names in `scripts/generate.py` before running a batch.

**404 on model repo** — the `prince-canuma/LTX-2.3-*` names may have been renamed. Check `https://huggingface.co/prince-canuma` and `https://huggingface.co/Lightricks` for current variants.

**Out of memory mid-generation** — unlikely on 128 GB but possible if Logic is open with a big session. Quit other apps, or drop to `--pipeline distilled` and 896×512.

**First-frame artefact / overbaked first frame** — not a specifically documented "first-frame glitch", but LTX-2 has known VAE artefacts (the original distilled VAE shipped broken and was replaced; tiled VAE encoding can produce temporal-seam ghosting — see ComfyUI issue #11767). If you see a bad opening frame or seam artefact, trim the first few frames in the NLE. Don't rely on this as a reflex; inspect clips first.

**Motion doesn't feel synced to the music** — LTX-2.3's audio conditioning affects motion energy and broad structure, not literal beat sync. If tighter sync matters, switch the conditioning audio from a pad/drone stem to a percussive stem. Or accept that the sync is atmospheric and do any hard beat cuts manually in the NLE.

**Model generates people despite `no figures`** — add to negative side of the prompt as well if `mlx-video` supports `--negative-prompt`. Otherwise reinforce in-prompt: `empty landscape, uninhabited, no humans, no animals`.

**ComfyUI fails to load LTX-2.3 nodes on Mac** — don't use ComfyUI for this on Mac. The native MLX path in this guide is the supported route. The CUDA/ComfyUI path is for the RTX 4090 box, not the laptop.

---

## 13. Reference parameter sets

| Use case                     | Pipeline            | Model repo                         | Size          | CFG  | Wall time / clip (M5 Max) |
|------------------------------|---------------------|------------------------------------|---------------|------|----------------------------|
| Fast iteration               | `distilled`         | `prince-canuma/LTX-2.3-distilled`  | 896×512       | 2.5  | 6–12 min                   |
| Review quality               | `distilled`         | `prince-canuma/LTX-2.3-distilled`  | 1280×720      | 3.0  | 15–25 min                  |
| Final quality                | `dev-two-stage-hq`  | `prince-canuma/LTX-2.3-dev`        | 1280×720      | 3.0  | 45–90 min                  |
| Hero shot                    | `dev-two-stage-hq`  | `prince-canuma/LTX-2.3-dev`        | 1536×864      | 4.0  | 90–150 min                 |

Higher CFG = tighter adherence to the prompt at the cost of motion quality. 3.0 is a good default; 4.0+ starts to look stiff.

---

## 14. What this guide deliberately does not do

- **Does not** ship clips to a commercial music-video-generator service. The whole point is that the user is escaping the per-second pricing trap.
- **Does not** attempt lip-sync or performance video. That is Wan 2.2 S2V territory and a different pipeline; not relevant for ambient/electronic instrumental work.
- **Does not** colour-grade the clips inside the model. Grading belongs in the NLE against the full timeline.
- **Does not** do final assembly. The cut is a creative decision, not a batch job.

---

*Guide current as of April 2026, based on `mlx-video` `main` branch and LTX-2.3 checkpoints on Hugging Face. Model repo names and CLI flags in the `mlx-video` ecosystem shift on roughly a monthly cadence — verify with `--help` and the Hugging Face pages before each new project.*
