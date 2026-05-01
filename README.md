# macvideo

A music video generation pipeline for Apple Silicon. Given a `.wav` song and its lyrics, `macvideo` produces a full-length, per-scene LTX-2 rendered music video with a coherent visual language.

Running locally on an M-series Mac. No ComfyUI, no server GPU, no cloud rendering.

## How it works

```
.wav + lyrics
   │
   ▼
[ WhisperX forced alignment ]     ← word-level timings via wav2vec2
   │
   ▼
[ Shot plan ]                     ← one shot per lyric line
   │
   ▼
[ Three-pass prompt pipeline ]
   │   Pass A — world brief (song-level: filter, abstraction, narrator)
   │   Pass C — storyboard    (song-level: beats, arcs, camera intents)
   │   Pass B — per-shot image prompt (identity-chained to prior keyframes)
   ▼
[ Gemini 3.1 flash image preview ]     ← landscape keyframes, aspect-ratio locked
   │
   ▼
[ LTX-2.3 dev-two-stage ]         ← mlx-video on Apple Silicon, first-frame conditioning
   │
   ▼
[ ffmpeg alignment pass ]         ← A+B1+C policy: trim/pad to keep audio-visual sync
   │
   ▼
final .mp4
```

## Layout

```
.
├── config/              # Global pipeline config (styles, model pins)
├── docs/                # Research notes, plans, song reports
├── editor/              # Storyboard editor (Python backend + React frontend)
│   ├── server/          # FastAPI + SQLite store + importer + regen queue
│   └── web/             # React 19 + Vite + SWR + Playwright
├── music/               # (gitignored) source .wav + .txt lyric files
├── pocs/                # 29 proof-of-concept experiments (see below)
└── pyproject.toml       # Python deps managed by uv
```

## POCs (in execution order)

Each `pocs/NN-name/` directory has a `README.md` (what we tried), `scripts/` (code), and usually a `RESULT.md` (what we learned). Outputs are gitignored.

| # | Topic | Status |
|---|---|---|
| 1 | LTX smoke test | ✓ |
| 2 | LTX audio-conditioned | ✓ |
| 3 | LTX image-to-video | ✓ |
| 4 | LTX chained multi-shot | ✓ |
| 5 | Gemini single still | ✓ |
| 6 | Gemini identity chain | ✓ |
| 7 | WhisperX forced alignment (100% word accuracy) | ✓ |
| 10 | Filter styles (cyanotype, stained glass, papercut...) | ✓ |
| 11 | Scene cut detection | ✓ |
| 12 | Per-shot timing refinement | ✓ |
| 13 | Combined lyric+beat shots | ✓ |
| 14 | Abstraction parameter | ✓ |
| 15 | Gap interpolation | ✓ |
| 16 | Storyboard pipeline | ✓ |
| 17 | Filter gallery | ✓ |
| 18 | Filter chooser (narrator-driven) | ✓ |
| 19 | Abstraction gallery | ✓ |
| 20 | Audio-influenced prompts | ✓ |
| 21 | 1080p feasibility probe | ✓ |
| 22 | Audio-aligned timeline | ✓ |
| 23 | Snap shots to onset events | ✓ |
| 24 | Event-densified shot plan | ✓ |
| 25 | First+last frame conditioning (mlx-video PR #23) | ✓ |
| 26 | Deforum-style fake-zoom | ✓ |
| 27 | Emerge transition (narrator out of scene) | ✓ |
| 28 | Zoom-morph transition (geometric crop + Gemini morph) | ✓ |
| 29 | Full-song render (3 songs: blackbird, chronophobia, busy-invisible) | in progress |

## Running the pipeline

### Prerequisites

- Apple Silicon Mac (M1 or later) with ≥32GB unified memory
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- [bun](https://bun.sh/) (for the editor's frontend)
- `.env` at repo root with `GEMINI_API_KEY=...`
- `ffmpeg` on `PATH`

### Product runtime boundary

The editor is the product runtime. POCs under `pocs/` are reference material
only; product behavior promoted from a POC must be re-designed into
product-owned code under `editor/` rather than copied or executed directly.

During the staged refactor, any temporary runtime dependency on POC-era scripts
or POC-shaped output files must be listed in
`docs/architecture/temporary-legacy-dependencies.json` with an owner story and
removal condition. The architecture tests fail for new unlisted references.

### Clean Checkout Setup

From a fresh clone:

```sh
uv sync --dev
cd editor/web && bun install && cd ../..
uv run python scripts/check_dev_environment.py --mode dev
```

Diagnostics report required tools (`uv`, `bun`, `ffmpeg`), optional model
credentials/adapters, local songs, and which workflows are affected. Missing
Gemini credentials or render adapters block the heavyweight product actions,
but the editor and fake-backed tests can still run.

If no songs are present, add `music/<slug>.wav` and matching
`music/<slug>.txt`, then start the editor and use import/refresh. The `music/`
directory is intentionally gitignored.

### Storyboard editor

For hand-tuning prompts, filters, and takes on a real song, use the editor:

```sh
scripts/start_editor.sh
```

Visit `http://localhost:5173/`. The editor:

- Imports existing `outputs/<slug>/` trees as SQLite rows (songs + scenes + takes).
- Serves assets with HTTP Range support (critical — without it audio scrubbing silently breaks).
- Lets you edit a scene's beat / camera intent / image prompt and propagates staleness to the identity chain.
- Runs regen stages against the backend queue.
- Produces final videos via `/api/songs/<slug>/render-final`.

`scripts/start_editor.sh` always stops listeners on ports `8000` and `5173`
before starting the backend and Vite. It removes fake script overrides only for
the backend command, so local development does not inherit stale test settings.
Use `scripts/stop_editor.sh` to tear down those ports explicitly.

### Test Taxonomy

```sh
uv run pytest editor/server/tests/                  # backend unit/integration, fake adapters where marked
cd editor/web && bun run test:unit                  # frontend unit/component tests
cd editor/web && bun run test:e2e:fake              # Playwright with fake generation/render adapters
cd editor/web && bun run test:e2e:product:diagnose  # dependency diagnostics for real product E2E
uv run pytest editor/server/tests/test_architecture_boundary.py
```

The current Playwright suite is **fake-backed E2E**: it starts real backend and
frontend processes, uses isolated temp data, and validates product orchestration
with fake adapters. It is not a claim that Gemini/LTX/WhisperX/ffmpeg-heavy
workflows completed with real model outputs. True product E2E requires the
diagnostics to show the relevant credentials, adapters, local tools, and sample
data are available.

Browser tests never reuse or stop the local dev servers on ports `8000` and
`5173`. `editor/web/scripts/e2e.sh` runs a separate test stack on
`EDITOR_E2E_API_PORT` and `EDITOR_E2E_WEB_PORT` (defaults: `18000` and
`15173`) and only tears down those test ports. `editor/web/tests/e2e/setup_backend.sh`
creates a fresh temp database, music root, and outputs root for each invocation.

## Hard lessons baked in

Written here so I don't have to learn them again.

- **LTX interpolates appearance, not camera pose.** If you want a zoom transition, you have to provide geometrically-cropped start and end frames. The model won't invent the camera motion from a prompt alone. (POC 28 v2.)
- **Audio element is the single source of truth for playhead.** Dual-source-of-truth playhead state in the preview layer guarantees drift. The editor lets the `<audio>` element drive and subscribes to `timeupdate` / `seeked`. (preview.html saga; editor story 2.)
- **HTTP Range support is non-negotiable for audio seeking.** Without `206 Partial Content` responses, browsers silently ignore seeks and replay from zero. The editor's backend implements Range-aware static serving. (preview.html saga, four rounds of debugging.)
- **Gemini 3.1 flash image preview picks aspect per prompt.** Pass `imageConfig.aspectRatio="16:9"` explicitly — do NOT rely on the prompt. (Blackbird shipped; chronophobia produced 11 portrait keyframes before we caught it.)
- **Stick with flash unless you have a specific reason to use pro.** Pro offers "advanced reasoning" but the cost delta is real and flash outputs are already outstanding for the prompts this pipeline writes.
- **A+B1+C contiguous shot policy.** If a clip overshoots its lyric window, trim it; if it undershoots, pad with `ffmpeg tpad`. Never leave audio-visual drift to compound across a full song. (POC 29.)

## Model pins

- **mlx-video**: [`zhaopengme/mlx-video`](https://github.com/zhaopengme/mlx-video) at commit `a2046415` (PR #23 branch, adds `--end-image` / `--end-image-strength` for first+last-frame I2V). PR #24's VAE fix is patched in manually if not present.
- **LTX model**: `prince-canuma/LTX-2.3-dev` (HuggingFace)
- **Text encoder**: `mlx-community/gemma-3-12b-it-bf16`
- **Image model**: `gemini-3.1-flash-image-preview`
- **Forced alignment**: WhisperX + `wav2vec2-large-960h-lv60-self`

## License

Not yet specified. This is an experimental personal project.
