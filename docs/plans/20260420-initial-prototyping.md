# Initial prototyping plan — macvideo

**Last updated:** 2026-04-21 (POC 3 + 5 results)

**Maintenance instructions for future sessions:**
- Update the `Last updated` date at the top whenever you change this file.
- Check tasks off as `- [x]` when fully verified (code merged, test passing, output inspected). Do not mark partial work complete.
- Add new tasks under the appropriate stage as they emerge. Remove tasks that are superseded — keep the list lean, not archaeological.
- If a decision in **Locked decisions** changes, edit it in-place and append a dated line to **Changelog** at the bottom. Don't leave stale assumptions floating in the doc.
- Record open questions as they arise. Move them to closed (with the answer) or delete them as resolved.

---

## Context

Pipeline goal: .wav → dramatic, sparkling music video, Mac-local on M5 Max 128GB, automated rough-cut with NLE polish as the manual final step.

Companion docs (read these for the "why"):
- `docs/20260420-music-video-ltx23-mac.md` — clip generation engine spec
- `docs/20260420-pipeline-plan.md` — overall pipeline architecture and rationale

## Locked decisions (v1)

- **Orchestration:** native Python with `uv run`. No ComfyUI spine.
- **Image gen (keyframe stills):** Google Gemini `gemini-3.1-flash-image-preview` ("Nano Banana 2") via the Google GenAI SDK. Chosen over Flux.1-dev MLX for native multi-image identity consistency (no IP-Adapter plumbing needed). Preview model ID — verify against current Google docs before first batch and pin.
- **Video gen:** LTX-2.3 via `mlx-video`, pinned to a resolved commit SHA.
- **Audio:** Demucs `htdemucs_6s`, WhisperX large-v3 on vocals stem, librosa for structure.
- **LLM:** Google GenAI SDK, `gemini-3-flash-preview` for structure labelling, style picking/expansion, and shot planning. Preview model ID — verify against current Google docs and pin. Same SDK and API key as image gen, so auth is one-path.
- **Resolutions:** poc (512×320), iteration (896×512), final (1920×1080). 512×320 empirically confirmed at 30 s on M5 Max distilled (POC 1, 2026-04-21) — the main guide's §13 table understates speed by ~10×. Re-benchmark iteration and final before committing.
- **Styles:** papercut, watercolour, steampunk, pencil sketch, bubblegum. LLM picks **one** per song, expands once into concrete visual cues, every shot prompt inherits the expansion.
- **Lip-sync:** out of v1. Revisit ~2026-10 or when a CUDA box is available.
- **Cloud scope (updated 2026-04-20):** permitted for LLM (Anthropic) and image gen (Google Gemini) stages only. Video, audio prep, transcription, assembly remain local. No cloud lip-sync, no cloud video gen.
- **Web UI (if added later):** React 19.2 + bun + TypeScript.

## Key external references

- [LTX-2 prompting guide (official)](https://docs.ltx.video/api-documentation/prompting-guide) — use the 6-element paragraph structure, 4–8 sentences, under 200 words.
- [LTX-2.3 deltas](https://ltx.io/model/model-blog/ltx-2-3-prompt-guide) — longer prompts, richer audio descriptions.
- [Lightricks/LTX-2 GitHub](https://github.com/Lightricks/LTX-2)
- [Blaizzy/mlx-video](https://github.com/Blaizzy/mlx-video)
- [prince-canuma HF models](https://huggingface.co/prince-canuma)
- [WhisperX](https://github.com/m-bain/whisperX)
- [Demucs](https://github.com/facebookresearch/demucs)

---

## Stage 0 — Repo scaffolding

- [ ] `pyproject.toml` (uv, Python 3.11+), pinned deps: `whisperx`, `demucs`, `librosa`, `google-genai`, `pyyaml`, `mlx`, `mlx-video@<sha>` (currently `9ab4826`). **Requires `allow-direct-references = true` under `[tool.hatch.metadata]`** because mlx-video is a git URL dep.
- [ ] Document the Gemma 3 12B bf16 text encoder as an explicit prerequisite: `mlx-community/gemma-3-12b-it-bf16` (~24 GB download, MLX-native, not gated). `google/gemma-3-12b-it` is gated and not needed.
- [ ] Document num-frames constraint: must equal `1 + 8*k`. Formula: `num_frames = ((int(seconds * fps) - 1) // 8) * 8 + 1`.
- [ ] Runbook note: LTX-2.3 fails with "Failed to create Metal shared event" if another MLX process is running. Kill competitors before batch.
- [ ] Directory layout: `scripts/`, `config/`, `data/{tracks,stems,lyrics,structure,shotplans,keyframes,clips,cuts,logs}/`, `tests/`
- [ ] `config/pipeline.yaml` — resolution profiles, model repos, paths
- [ ] `config/styles.yaml` — bare-word style list (expansion is per-song, not pre-cached)
- [ ] `.gitignore` — venv, weights, clips, stems, logs, .DS_Store
- [ ] `README.md` — quickstart, references to this plan and the companion docs
- [ ] First commit and push to `origin/main`

## Stage 1 — Audio prep

- [ ] `scripts/prep_audio.py <track>` — normalise to 48kHz stereo s16 WAV
- [ ] Run Demucs `htdemucs_6s` → 6 stems in `data/stems/<track>/`
- [ ] Test: one 3–4 min track produces 6 stems, vocals stem inspected for bleed

## Stage 2 — Lyric transcription (WhisperX)

- [ ] `scripts/transcribe.py <track>` — WhisperX large-v3 on vocals stem
- [ ] Output `data/lyrics/<track>.json` with word-level + line-level timings
- [ ] Document manual-correction workflow for the 5–15% of words Whisper gets wrong on vocals-heavy material
- [ ] Test: transcription of test track, eyeball accuracy against known lyrics

## Stage 3 — Structure analysis

- [ ] `scripts/structure.py <track>` — librosa beat/tempo/bar grid + segment boundaries from full mix
- [ ] LLM pass: label sections (intro/verse/pre-chorus/chorus/bridge/solo/outro) using lyrics + audio boundaries
- [ ] Flag "big moments" (drop, last chorus, key change)
- [ ] Output `data/structure/<track>.json`
- [ ] Test: produces plausible segmentation on test track

## Stage 4 — Shot planning (LLM director)

- [ ] `scripts/plan_shots.py <track>`
- [ ] **4a:** LLM picks one style from `config/styles.yaml` given lyrics + structure
- [ ] **4b:** LLM expands chosen style word → concrete visual cues (subject descriptors, lighting, texture, palette, lens). Cached per track.
- [ ] **4c:** LLM generates shot list: `{id, start_t, end_t, prompt, chain_from_previous (bool), audio_source_stem}`
- [ ] Prompt template enforces LTX-2.3 structure: flowing paragraph, present tense, 4–8 sentences, under 200 words, uses documented camera vocabulary (*follows, tracks, pans across, circles around, tilts upward, pushes in, pulls back, overhead view, handheld movement, over-the-shoulder, wide establishing shot, static frame*)
- [ ] Default `chain_from_previous: false`; LLM sets true for held moments, slow pushes, verse-to-chorus continuity
- [ ] Cap hero-shot density (~10–15%) in the prompt instruction
- [ ] Output `data/shotplans/<track>.yaml`
- [ ] Test: eyeball the shot plan on test track *before any generation*

## Stage 5a — Keyframe stills (Gemini `gemini-3.1-flash-image-preview` / Nano Banana 2)

- [ ] Verify exact model ID against current Google docs — preview IDs rotate. Pin in config once confirmed.
- [ ] API key management: `GEMINI_API_KEY` in env, never in repo; document in README.
- [ ] `scripts/keyframes.py <track>` — one still per `chain_from_previous: false` shot
- [ ] Resolution driven by `--profile` flag (Gemini output resized/cropped to target if the API doesn't expose exact dimensions)
- [ ] **Identity-consistency workflow:** first shot generates the performer(s) fresh; subsequent shots pass prior keyframe(s) as reference images so the same performer renders across the track
- [ ] Budget guard: per-track image-gen cost ceiling in config; abort batch with loud warning if exceeded
- [ ] Output `data/keyframes/<track>/<shot_id>.png`
- [ ] Log prompt + model + cost per image to `data/logs/<track>/keyframes.jsonl` for audit
- [ ] Test: still generates for one shot; second shot with prior as reference preserves performer identity

## Stage 5b — Clip generation (LTX-2.3)

- [ ] Adapt `scripts/generate.py` from `docs/20260420-music-video-ltx23-mac.md`
- [ ] Per-shot `--num-frames` must satisfy `1 + 8*k`. Formula: `((int((end_t - start_t) * fps) - 1) // 8) * 8 + 1`
- [ ] For `chain_from_previous: false`: I2V from `data/keyframes/<track>/<shot_id>.png` via `--image` (+ `--image-strength`, `--image-frame-idx`)
- [ ] For `chain_from_previous: true`: condition on previous clip's last frame via `--image` + `--image-frame-idx 0`
- [ ] Audio: **only for dev-family pipelines** (distilled has no audio CFG and is inert on audio content — see POC 2). Slice selected stem to `[start_t, end_t]`, pass as `--audio-file`.
- [ ] `--skip-existing` resume semantics
- [ ] Output `data/clips/<track>/<shot_id>.mp4`
- [ ] **Smoke test at 1920×1080** to validate `final` profile is feasible on M5 Max
- [ ] Test: 5 shots end-to-end at `poc` profile, then `iteration`

## Stage 6 — Timeline assembly

- [ ] `scripts/assemble.py <track>` — ffmpeg concat demuxer in shot order
- [ ] Overlay original master WAV as audio track
- [ ] Hard cuts on shot boundaries (no transitions in v1)
- [ ] Output `data/cuts/<track>_rough_<profile>.mp4`
- [ ] Test: runs end-to-end, output plays in QuickLook with audio synced

## Cross-cutting

- [ ] Resolution profile system: `--profile poc|iteration|final` maps via `config/pipeline.yaml`
- [ ] Per-stage logging to `data/logs/<track>/<stage>.log`
- [ ] `scripts/run_pipeline.py <track> --from <stage> --to <stage>` orchestrator
- [ ] One test per stage on a 30-second test clip to keep CI feedback fast

---

## Out of scope for v1

- **Lip-sync** (local Mac quality insufficient, no cloud by decision)
- **NLE polish automation** — genuinely manual
- **Transitions beyond hard cuts** — crossfades, match-on-action belong in the NLE
- **Colour grading automation** — unified grade is an NLE pass
- **Beat-accurate cut snapping** — Whisper word boundaries are close enough for v1
- **Web UI** — none planned; stack decided if added

## Open questions (to close empirically)

### Closed by POC 1 (2026-04-21)
- [x] `--negative-prompt` supported but dev-pipeline only. Distilled iteration pass cannot use negatives. Prompt template must branch by pipeline.
- [x] Keyframe/last-frame conditioning: `--image` + `--image-strength` + `--image-frame-idx` all present. POC 3 and POC 4 unblocked.
- [x] `mlx-video` CLI flag reconciliation: recorded in `pocs/01-ltx-smoke/RESULT.md` and the guide.

### Still open
- [ ] Does LTX-2.3 run at 1920×1080 on M5 Max without OOM, and at what wall-time? POC 1 confirmed 512×320 at 30 s; extrapolating to 1080p is risky. Smoke-test before committing to the `final` profile.
- [ ] Empirical wall-time at `iteration` (896×512) and `final` (1920×1080). Add a sub-test in POC 2 or a dedicated benchmark run.
- [ ] Gemini `gemini-3.1-flash-image-preview` and `gemini-3-flash-preview` current model IDs, pricing, rate limits. Verify against Google docs at stage 3/4/5a setup.
- [ ] Gemini identity-persistence quality across 30+ shots of the same performer — does drift creep in, and at what shot count? POC 6.

## Changelog

- 2026-04-20 — Initial plan.
- 2026-04-20 — Keyframe stills switched from Flux.1-dev (local MLX) to Gemini `gemini-3.1-flash-image-preview` ("Nano Banana 2"). "No cloud" principle narrowed from absolute to "no cloud for video, audio, or lip-sync stages; LLM and image gen via cloud APIs permitted." Rationale: native multi-image identity consistency eliminates IP-Adapter plumbing.
- 2026-04-20 — LLM switched from Anthropic Claude Opus 4.7 to Google `gemini-3-flash-preview`. Rationale: text spend is trivial; consolidating LLM + image gen on a single vendor (Google GenAI SDK) simplifies auth, billing, and dependencies. Video stays local where the real compute lives.
- 2026-04-21 — POC 1 passed. Findings in `pocs/01-ltx-smoke/RESULT.md`: LTX-2.3 distilled runs at 512×320 in 30 s on M5 Max (guide claimed 6–12 min — pessimistic by ~10×). Text encoder switched from `google/gemma-3-12b-it` (gated, early-access form) to `mlx-community/gemma-3-12b-it-bf16` (MLX-native, ungated). `num-frames` must be `1 + 8*k`. `--negative-prompt` is dev-pipeline only.
- 2026-04-21 — POC 2 passed with a nuance. Findings in `pocs/02-ltx-audio-cond/RESULT.md`: audio conditioning is **inert in distilled** (no CFG path for audio, confirmed in `denoise_distilled` source) and **content-sensitive in dev** (verified empirically — same prompt+seed, different audio → substantively different scenes). Architectural implication: `--audio-file` is gated by pipeline — skip for distilled/iteration, use for dev-family/final. Distilled is not just a faster dev; it is a different decoder trained for CFG-less inference, so audio conditioning and negative prompts don't work there regardless of flags.
- 2026-04-21 — POC 3 passed (I2V on distilled). Findings in `pocs/03-ltx-i2v/RESULT.md`: `--image` + `--image-strength` + `--image-frame-idx` anchor frame 0 on the supplied still and motion unfolds per prompt. Works on distilled — image conditioning is applied to the initial latent state, not as CFG guidance, so CFG-less pipelines still honour it. Required pinning mlx-video to PR #24 HEAD (`nopmobiel/mlx-video@a8cd1db7`) because Blaizzy's `main@9ab4826` has a VAE encoder topology bug for LTX-2.3. Revert once PR #24 merges upstream.
- 2026-04-21 — POC 5 passed (Gemini `gemini-3.1-flash-image-preview`). Findings in `pocs/05-gemini-still/RESULT.md`: preview model ID valid, 18 s latency, 1120 image tokens per still, strong prompt adherence on a steampunk test prompt. Identity-consistency check (POC 6) still pending.
