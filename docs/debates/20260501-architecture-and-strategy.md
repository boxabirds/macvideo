# Architecture Review and Strategy Debate

Date: 2026-05-01

This document is an architecture audit of the current `macvideo` codebase and a fictional strategy debate about how to turn the current proof-of-concept lineage into a supportable open-source application.

Important note: the debate section is not a real transcript and does not quote John Carmack, Grady Booch, or Andrej Karpathy. It is a simulated discussion using broad, public engineering archetypes associated with systems pragmatism, software architecture discipline, and AI product iteration.

## Executive Summary

The codebase is recoverable, but it is not yet architecturally clean. The current product has useful bones: a FastAPI backend, a SQLite store, a React editor, a regeneration queue, transcript correction concepts, and some product-owned audio wrappers. The main failure mode is that the application still behaves like a UI wrapped around a POC file pipeline.

The most important architectural policy is:

> POCs are reference material only. Product runtime code must not import, execute, shell out to, cache beside, or operationally depend on files under `pocs/`. Product behavior derived from POCs must be re-designed into product-owned modules, services, adapters, schemas, and tests. It must not be copied verbatim.

Refactoring should proceed only under that broader policy. The target architecture should be a modular monolith with explicit domain objects, a single backend-owned workflow state machine, SQLite as source of truth, product-owned pipeline services, and adapters for heavyweight external engines such as Demucs, WhisperX, Gemini, image generation, and video rendering.

## Review Scope

Reviewed areas:

- Repository structure and project guidance.
- `README.md` and `AGENTS.md`.
- Backend FastAPI routers and app startup.
- Backend importer, SQLite store, pipeline stages, queue, final render, and asset serving.
- Frontend React API client, workflow state helper, pipeline panel, storyboard, and transcript-related UI.
- Test structure and coverage shape.
- Runtime dependencies on `pocs/`.

This was a codebase review and architecture assessment. It was not a full semantic verification of every pipeline stage, model prompt, or UI workflow.

## As-Is Architecture

The application currently has these major pieces:

- `editor/server`: FastAPI backend, SQLite persistence, import logic, pipeline stage execution, regeneration queue, and asset serving.
- `editor/web`: React/Vite frontend with editor panels, storyboard controls, transcript editing surfaces, and API access.
- `music`: input media.
- `pocs`: proof-of-concept experiments, including the historic full-song pipeline.

Current logical dependency flow:

```text
React UI
  -> FastAPI routers
    -> SQLite store
    -> importer from output JSON
    -> pipeline queue
      -> product wrappers for some audio steps
      -> POC scripts for several generation/rendering steps
    -> filesystem assets from music/ and POC output directories
```

The architecture has moved toward a real product, but the dependency graph still allows POC code and POC-shaped artifacts to define runtime behavior.

## Strengths

The codebase has enough structure to recover:

- The backend is organized around FastAPI routers rather than a single ad hoc script.
- SQLite persistence exists and models songs, scenes, takes, regeneration runs, transcript corrections, and finished videos.
- Regeneration work is separated from request handling through a queue.
- Stage and regeneration statuses exist as explicit concepts.
- Range-aware media serving is present, which matters for an editor.
- The frontend has test coverage and has started centralizing workflow state logic.
- Product-owned wrappers now exist for some audio pipeline concerns, including Demucs separation and WhisperX transcription.
- The code already has domain vocabulary: song, scene, take, transcript, world, storyboard, image prompt, keyframe, clip, final video.

These are not trivial assets. The codebase is messy, not empty.

## Critical Liabilities

### 1. Runtime Still Depends on POCs

The largest architectural problem is not style; it is ownership. Product runtime code still calls into the POC tree.

Examples found during review:

- Pipeline stage code refers to the POC script root.
- World, storyboard, image prompt, keyframe, clip, and final render paths are still connected to POC scripts.
- Some transcript/shot behavior still uses POC-derived script paths or helper loading.
- Tests still exercise some POC script behavior as if it were product behavior.
- Default output location is still under `pocs/29-full-song/outputs`.

This violates the intended product boundary and explains why fixes can feel fragile. A renamed wrapper or patched script path does not change the architecture if the product still depends on POC-owned runtime behavior.

### 2. JSON Artifacts Are Acting Like Operational State

The product has SQLite, but it still expects files such as:

- `shots.json`
- `character_brief.json`
- `storyboard.json`
- `image_prompts.json`

These are acceptable as import/export artifacts or cache material. They should not be required as the authoritative runtime state of the product.

When the app fails because a JSON file is missing, the architecture is telling the user that the real source of truth is still the POC output folder, not the product database.

### 3. State Machine Is Distributed

Workflow state appears in several layers:

- Backend song status computation.
- Backend stage dependency checks.
- Pipeline stage execution behavior.
- Frontend workflow helper logic.
- UI gating logic in components.

Some duplication is normal, but the current system risks disagreement. The product needs one backend-owned workflow state machine that computes allowed actions, current stage state, dependencies, retry eligibility, progress, and user-facing error categories. The frontend should render that state rather than independently rediscover it.

### 4. Product Services Are Not Clear Enough

The product has pipeline functions, but not yet a clean application-service boundary. Concepts such as transcription, shot planning, world generation, storyboard generation, image prompting, keyframe generation, clip rendering, and final video rendering should be explicit product services with stable contracts.

The services should own product behavior. Adapters should call external tools or models.

### 5. Open-Source Readiness Is Mixed

For an open-source app, a new contributor should be able to answer:

- What is product code?
- What is reference POC code?
- What are required external tools?
- What data is stored in SQLite?
- What data is generated as an artifact?
- How do I run a minimal deterministic smoke test?
- Which tests use fakes and which tests are true end-to-end?

The current repository does not make those answers crisp enough.

### 6. Frontend Components Are Too Large

Some frontend components are large enough that product behavior, view state, workflow gating, and presentation are easy to mix. The frontend should be decomposed around editor surfaces and backend-provided workflow state, not around legacy stage mechanics.

This is not the first problem to fix, but it will matter as the app grows.

## Architecture Quality Assessment

| Area | Current Grade | Assessment |
| --- | --- | --- |
| Product potential | B+ | The domain is strong and the current app has useful foundations. |
| Runtime boundary hygiene | D | POC runtime dependencies remain a structural problem. |
| Domain model | C+ | Key entities exist, but JSON artifacts still compete with SQLite. |
| Workflow state | C- | Status exists, but the state machine is not clearly singular. |
| Pipeline architecture | C- | Useful pieces exist, but service and adapter boundaries are not firm. |
| Test investment | B- | There are many tests, but categories and architectural enforcement are uneven. |
| Frontend architecture | C+ | Functional, but large components and local gating logic create drift risk. |
| Open-source readiness | C- | The project can become supportable, but install/run/test boundaries need work. |

Overall: recoverable, but only if the next phase is architecture-led rather than patch-led.

## Architectural Policy

The following policy should govern refactoring.

### POC Boundary

POCs under `pocs/` are reference sources only.

Product runtime code must not:

- Import files from `pocs/`.
- Execute scripts from `pocs/`.
- Shell out to scripts from `pocs/`.
- Cache beside scripts in `pocs/`.
- Depend on POC output directories as the default product data location.
- Treat POC JSON files as authoritative product state.
- Copy POC files verbatim into `editor/` and call that a migration.

Product code may:

- Read POC code during development to understand algorithms, prompt shape, media flow, or historical intent.
- Re-implement required behavior in product-owned modules.
- Add tests that prove the product-owned implementation satisfies product contracts.
- Keep POC-to-product import tools for migration, as long as those tools are not required for normal runtime operation.

### Product-Owned Runtime

All runtime behavior should live under `editor/`.

The pipeline should expose product services such as:

- `TranscriptionService`
- `ShotPlanningService`
- `WorldService`
- `StoryboardService`
- `ImagePromptService`
- `KeyframeService`
- `ClipRenderService`
- `FinalRenderService`

Each service should accept product domain inputs and write product domain outputs. Files are artifacts, not state.

### SQLite as Source of Truth

SQLite should be the canonical store for:

- Song metadata.
- Scene boundaries.
- Scene transcript text and word timings.
- Transcript corrections.
- Stage runs and errors.
- World description.
- Storyboard beats.
- Image prompt records.
- Keyframe records.
- Clip records.
- Final render records.

Generated media files can stay on disk, but the database should record their identity, purpose, version, status, and relationship to product entities.

### Single Workflow State Machine

The backend should own one state machine that answers:

- What stage is each song in?
- Which actions are currently allowed?
- Why is an action blocked?
- Is the current failure retryable?
- What user-facing progress should be shown?
- What downstream artifacts are stale?
- What should be invalidated when the user edits a transcript, world brief, storyboard beat, image prompt, keyframe, or clip?

The frontend should consume a workflow view model from the backend and render it. It should not independently recreate product stage rules.

### Ports and Adapters

External dependencies should sit behind adapters:

- Audio separator adapter.
- Transcription adapter.
- LLM text adapter.
- Image generation adapter.
- Video rendering adapter.
- Media probing/transcoding adapter.
- Filesystem artifact adapter.

Adapters can be slow, local, remote, expensive, or flaky. Product services should be testable without them.

### Test Boundary Policy

Tests should be explicitly categorized:

- Unit tests may use fakes.
- Adapter contract tests may use controlled fixtures.
- Integration tests should use real SQLite and real product modules.
- Product E2E tests should not use fake pipeline results when claiming to validate the end-to-end product path.
- Slow model/tool tests may be optional, marked, and documented, but the default suite must still enforce architecture and product contracts.

## Simulated Debate

### Opening Positions

**Moderator:** We are assessing a proof-of-concept that became an app. It has a React editor, FastAPI backend, SQLite store, queue, model pipeline, and a history of POC scripts. The user wants an open-source product others can run. What architecture should it have?

**Carmack-style perspective:** The first thing I care about is making the program understandable when it runs. Right now too much behavior is indirect. If clicking a button eventually shells out to some old script in a POC directory, then the product does not own that behavior. You can add abstractions, but if the actual runtime path is still a maze, you have not improved the system. Make the pipeline direct, deterministic, and observable.

**Booch-style perspective:** I agree on ownership, but I would name the deeper issue as missing architectural decisions. The code has entities and mechanisms, but it lacks a governing architecture. A product must define its components, their responsibilities, allowed dependencies, and the invariants that tests enforce. Otherwise every bug fix becomes a local patch against an unstable conceptual model.

**Karpathy-style perspective:** For AI-heavy apps, you also need to accept that the pipeline is probabilistic and operationally heavy. The architecture should make model boundaries explicit. You need fast local iteration, but you also need evals, artifacts, prompts, and error states that users can inspect. The user is not just running code; they are supervising a creative pipeline.

### On POCs Becoming Product Code

**Moderator:** How should the project treat existing POCs?

**Carmack-style perspective:** POCs are a mine for ideas, not a runtime dependency. Read them. Learn the minimum useful algorithm. Then write the product version in the product tree. The dangerous move is pretending a path rename or wrapper has productized the code. If the POC script still controls control flow, it is still the product.

**Booch-style perspective:** The policy should be explicit and testable. The architecture should define forbidden dependencies. A static test should fail if product runtime code references `pocs/`. This is not bureaucracy; it is how the team preserves architectural intent.

**Karpathy-style perspective:** I would add that POC prompts and model hacks often encode valuable discoveries. Do not throw away that knowledge. Extract it into prompt templates, schemas, eval fixtures, and documented model contracts. But do not preserve accidental file layout, positional arguments, or notebook-era assumptions.

### On JSON Files Versus Database State

**Moderator:** The app still relies on JSON outputs such as `shots.json`. Is that acceptable?

**Carmack-style perspective:** Files are fine when they are artifacts. They are bad when the app silently depends on them as state. If `shots.json` missing breaks world generation, the app's source of truth is not the database. Pick one source of truth.

**Booch-style perspective:** The domain model should decide this. A scene, transcript, storyboard beat, keyframe, and clip are domain concepts. They belong in the persistent model. JSON can be an interchange representation, but not the architecture's spine.

**Karpathy-style perspective:** For AI workflows, I still want artifacts. They are useful for reproducibility, debugging, and sharing. But they should be derived artifacts with provenance. The database should know which prompt, model, input transcript, and adapter version created them.

### On the State Machine

**Moderator:** Users are seeing actions available before prerequisites exist, unclear stage labels, and failures without useful errors. What should change?

**Booch-style perspective:** This is a state-machine problem. The state machine should be centralized, explicit, and tested exhaustively. The UI should receive allowed actions and blocked reasons from the backend. If the storyboard is missing, the backend should say keyframe generation is blocked because world and storyboard are incomplete.

**Carmack-style perspective:** Keep the state machine small. A table of stage dependencies and invalidation rules is often enough. Avoid a complex framework unless it buys clarity. The user should be able to print the current song state and understand why each button is enabled or disabled.

**Karpathy-style perspective:** Add progress and partial outputs as first-class state. AI stages are slow. For transcription, show processed duration over total duration. For generation stages, show what input is being used and what artifact is expected. The state machine should support human supervision, not just job completion.

### On Pipeline Services

**Moderator:** What should replace direct POC script execution?

**Carmack-style perspective:** Product-owned command functions. They should take explicit inputs and write explicit outputs. No hidden global directories. No magic relative path assumptions. No unclear positional command-line contracts.

**Booch-style perspective:** I would define application services with ports. For example, the `WorldService` depends on a transcript repository, a scene repository, and an LLM port. The implementation may call Gemini today, but the service contract is product-owned.

**Karpathy-style perspective:** The AI adapters need structured input and output schemas. Do not just pass blobs of text between stages. For prompts, keep templates versioned. For outputs, validate schemas and store failures with enough context to reproduce them.

### On Testing

**Moderator:** What tests are necessary before major refactoring?

**Booch-style perspective:** Tests must reflect architecture, not just behavior. I would require policy tests, state-machine tests, service contract tests, repository integration tests, API tests, UI tests, and true product E2E smoke tests.

**Carmack-style perspective:** I want small tests that fail at the exact boundary. A test that says "product code cannot reference POC runtime paths" catches a whole class of failure. A test that runs world generation from DB state and proves it never looks for `shots.json` is more useful than another broad UI test.

**Karpathy-style perspective:** Include eval-style tests for model-facing stages. You do not need exact image output in CI, but you can test prompt assembly, schema validation, fallback behavior, and human-edit preservation. For expensive real model tests, make them optional but documented.

### On Open-Source Supportability

**Moderator:** The user wants others to run this as an open-source app. What does that imply?

**Karpathy-style perspective:** The first-run experience matters. People need to know which models are required, which are optional, what runs locally, what uses an API key, and what hardware is expected. Heavy AI apps need a graceful degraded mode and clear diagnostics.

**Carmack-style perspective:** Make the local path deterministic. A developer should be able to run setup, import a sample song, and execute a minimal pipeline without old servers, inherited shell variables, or hidden state. If a dependency is missing, fail with a precise check before the job starts.

**Booch-style perspective:** Document the architecture. Not a giant essay, but a living decision record: product runtime boundaries, module responsibilities, persistence rules, test categories, and extension points. Open-source contributors need constraints as much as they need instructions.

### Converged Recommendation

**Moderator:** What architecture should this project adopt?

**Carmack-style perspective:** A modular monolith. Keep one process unless forced otherwise. Make the runtime path direct. Delete POC runtime dependencies. Put each heavy external tool behind a small adapter.

**Booch-style perspective:** A modular monolith with a clear domain model, application services, repositories, adapters, and one workflow state machine. The important part is not the number of processes; it is the enforcement of boundaries.

**Karpathy-style perspective:** And treat AI stages as product workflows, not scripts. Store provenance, progress, prompts, model versions, structured outputs, and editable human corrections. The product is the human-in-the-loop system around the models.

**Moderator:** The consensus is a product-owned modular monolith with explicit AI pipeline adapters, SQLite-backed state, a centralized workflow engine, and architecture tests that prevent POC regression.

## Target Architecture

Recommended target:

```text
React Editor
  -> Product API
    -> Workflow State Machine
    -> Application Services
      -> Domain Repositories
      -> Artifact Store
      -> External Adapters
    -> SQLite
    -> Filesystem Artifacts
```

### Domain Layer

Owns product concepts:

- Song
- Scene
- Word timing
- Transcript correction
- Stage run
- World description
- Storyboard beat
- Image prompt
- Keyframe
- Clip
- Final video

This layer should not know about FastAPI, React, POC directories, Gemini, WhisperX, Demucs, or ffmpeg command details.

### Application Services

Own product workflows:

- Import song.
- Separate vocals.
- Transcribe audio.
- Plan scenes and word timings.
- Generate world description.
- Generate storyboard.
- Generate image prompts.
- Generate keyframes.
- Render clips.
- Render final video.
- Apply transcript corrections and invalidate dependent artifacts.

Application services should be testable with in-memory or test SQLite repositories and fake adapters.

### Adapter Layer

Owns messy external integration:

- Demucs adapter.
- WhisperX adapter.
- Gemini text adapter.
- Image generation adapter.
- Video renderer adapter.
- Media probe adapter.
- Filesystem artifact adapter.

Adapters should convert between product-owned requests/responses and external command/API behavior.

### Workflow State Machine

Owns:

- Stage dependency graph.
- Allowed actions.
- Blocked reasons.
- Retry behavior.
- Progress display.
- Invalidation rules.
- Terminal success/failure states.
- User-facing failure categories.

This state machine should be the only source used by both API responses and frontend workflow rendering.

## Refactoring Roadmap

### Phase 0: Freeze Architecture Policy

Goals:

- Amend `AGENTS.md` to explicitly ban copying POC files verbatim.
- Add a static architecture test that fails when product runtime code references `pocs/`.
- Clarify which tests may reference POCs as fixtures or migration inputs.
- Update README language so normal product setup does not present POC 29 as the application runtime.

Exit criteria:

- Product runtime dependency on POC paths is visibly tracked and cannot grow.
- New code has a clear rule to follow.

### Phase 1: Centralize Workflow State

Goals:

- Create one backend workflow state module.
- Move dependency rules, allowed actions, blocked reasons, retry categories, and progress mapping into that module.
- Make frontend consume backend-provided workflow view model.

Exit criteria:

- UI cannot offer keyframe or clip generation before prerequisites exist.
- Failed stages show retry icons and actionable errors.
- Stage labels distinguish current operation from broader workflow category.

### Phase 2: Make SQLite Authoritative for Transcript and Scene Planning

Goals:

- Replace runtime dependence on `shots.json` with database-backed scene and word timing records.
- Keep JSON import/export only as migration or diagnostic behavior.
- Preserve transcript correction behavior and timestamp integrity.

Exit criteria:

- World generation can start from DB state without looking for `shots.json`.
- Tests reproduce missing `shots.json` and prove product behavior still works.

### Phase 3: Product-Owned World, Storyboard, and Prompt Services

Goals:

- Reimplement world/storyboard/image-prompt generation as product services.
- Extract prompt knowledge from POCs without copying files verbatim.
- Store generated structures in SQLite with provenance.

Exit criteria:

- No runtime call to POC `gen_keyframes.py`.
- Prompt assembly and output schema validation have tests.
- Failed model responses are stored with useful diagnostic context.

### Phase 4: Product-Owned Keyframe, Clip, and Final Render Services

Goals:

- Replace POC keyframe and clip render calls with product adapters.
- Store render job inputs, outputs, and artifact references in SQLite.
- Support retry and invalidation from product state.

Exit criteria:

- No runtime call to POC `render_clips.py`.
- Final render can be reproduced from DB records and product artifact paths.

### Phase 5: Open-Source Hardening

Goals:

- Add deterministic setup and diagnostics.
- Document required and optional dependencies.
- Add sample data or a small smoke fixture.
- Separate fake-backed tests from true E2E tests.
- Add license and contribution guidance.

Exit criteria:

- A new contributor can clone, install, run tests, launch the editor, and understand which features require heavy models or API keys.

## MECE Test Plan

The following test categories are intended to be mutually exclusive and collectively exhaustive for the refactor.

### 1. Architecture Policy Tests

Purpose: enforce boundaries.

Required tests:

- Product runtime code must not reference `pocs/`.
- Product runtime code must not import modules from `pocs`.
- Product pipeline defaults must not point at POC output directories.
- New product services must live under product-owned modules.
- POC files may be referenced only by explicit migration/reference tests.

### 2. Domain Unit Tests

Purpose: validate pure product rules.

Required tests:

- Scene boundary validation.
- Word timing ordering and containment.
- Transcript correction preserves timestamp anchors.
- Artifact invalidation rules after transcript edits.
- Stage dependency graph correctness.
- Retry eligibility for failed stages.

### 3. Workflow State Machine Tests

Purpose: prove state is centralized and complete.

Required scenarios:

- Fresh imported song.
- Audio separated, transcript missing.
- Transcript complete, world missing.
- World complete, storyboard missing.
- Storyboard complete, prompts missing.
- Prompts complete, keyframes missing.
- Keyframes complete, clips missing.
- Clips complete, final render missing.
- Stage failed with retryable error.
- Stage failed with non-retryable configuration error.
- User edits transcript after downstream artifacts exist.

Assertions:

- Allowed actions are correct.
- Blocked actions include clear reasons.
- Progress labels are user-facing and stage-specific.
- Retry icons and actions are correct.
- Frontend receives all information needed to render without recreating rules.

### 4. Repository and SQLite Integration Tests

Purpose: prove persistence is authoritative.

Required tests:

- Import song creates canonical DB rows.
- Scene planning stores and reloads scenes and word timings.
- World/storyboard/prompt/keyframe/clip records round-trip.
- Stage run status and error context round-trip.
- Artifact records survive process restart.
- Missing JSON files do not break DB-backed workflows.

### 5. Application Service Tests

Purpose: validate product workflows with fake adapters.

Required tests:

- Transcription service writes transcript and timings.
- Scene planning service writes scenes without `shots.json`.
- World service reads DB transcript/scenes and writes world description.
- Storyboard service reads world and scenes and writes storyboard beats.
- Image prompt service reads storyboard and writes prompts.
- Keyframe service writes artifact records.
- Clip service writes clip records.
- Final render service writes final video record.

These tests may use fake adapters because they validate product orchestration, not external tools.

### 6. Adapter Contract Tests

Purpose: validate integration boundaries.

Required tests:

- Demucs adapter command validation and output discovery.
- WhisperX adapter argument contract and output schema parsing.
- LLM adapter request schema and response schema validation.
- Image adapter handles success, timeout, malformed response, and missing API key.
- Video renderer adapter handles input discovery and output reporting.

These tests should not pretend to validate the full product workflow.

### 7. Queue and Run Lifecycle Tests

Purpose: validate async execution.

Required tests:

- Enqueue stage run.
- Prevent duplicate incompatible runs.
- Emit progress events.
- Persist failure with error category and raw diagnostic.
- Retry from failed state.
- Cancel or supersede stale work where supported.
- Restart process and recover consistent run state.

### 8. API Tests

Purpose: validate backend contract.

Required tests:

- Song detail returns canonical workflow view model.
- Stage action blocked before prerequisites returns structured blocked reason.
- Stage action starts when prerequisites exist.
- Transcript correction endpoint invalidates downstream state.
- Asset endpoint serves registered artifacts only.
- Historical/imported data cannot masquerade as successful current product state.

### 9. UI Component Tests

Purpose: validate rendering and interaction, not pipeline execution.

Required tests:

- Stage progress renders operation-specific progress.
- Status pills do not show internal status noise.
- Blocked actions show prerequisite messages.
- Retry icon appears on retryable failures.
- Transcript editor supports correction without timestamp loss.
- Clicking a scene already playing does not restart playback.
- Word click starts playback at the selected word.
- Double-clicking collapsed scene title expands it.
- Loop toggle defaults on and affects playback behavior.

### 10. True Product E2E Smoke Tests

Purpose: validate the real product path.

Required tests:

- Launch known-good backend and frontend from clean setup scripts.
- Import a tiny sample song fixture.
- Run a minimal real product pipeline path as far as available local dependencies allow.
- Verify no POC runtime path is called.
- Verify UI shows progress and terminal state.

These tests must not use fake pipeline outputs when they are described as E2E. Slow optional E2E tests can be marked and documented.

### 11. Model and Prompt Eval Tests

Purpose: keep AI behavior supportable.

Required tests:

- Prompt templates render from product domain inputs.
- Output schemas reject malformed model responses.
- Golden small transcript produces structurally valid world/storyboard/prompt outputs with a fake or recorded adapter.
- Model failures produce actionable product errors.

Exact creative output should not be asserted unless the adapter is deterministic or recorded.

### 12. Migration and Import Tests

Purpose: preserve useful old data without keeping old runtime behavior.

Required tests:

- Import POC output fixture into SQLite.
- Missing optional POC artifact produces clear migration warning, not runtime crash.
- Imported records can be edited and regenerated using product services.
- Migration code is not required by normal product runtime.

### 13. Packaging and First-Run Tests

Purpose: support open-source users.

Required tests:

- Dependency check reports missing external tools before a pipeline run.
- Setup script creates isolated environment.
- Server start script uses known-good startup and teardown behavior.
- Test database is separate from development database.
- README quickstart commands work on a clean checkout with documented prerequisites.

## Immediate Recommendations

1. Update architecture policy in `AGENTS.md` to ban verbatim POC copying and to distinguish reference extraction from migration.
2. Add architecture tests before moving more runtime behavior.
3. Centralize workflow state before deeper UI work.
4. Move transcript and scene planning fully onto SQLite-backed product services.
5. Replace world/storyboard/prompt/keyframe/clip/final POC script calls one stage at a time, with tests for each boundary.
6. Reclassify tests so fake-backed tests are not called product E2E.
7. Rewrite quickstart documentation around the product app, not POC 29.

## Decisions to Record

Recommended architecture decision records:

- ADR 001: POCs are reference-only and forbidden from product runtime.
- ADR 002: SQLite is product source of truth; JSON files are artifacts/import-export only.
- ADR 003: Backend owns workflow state machine and allowed actions.
- ADR 004: Pipeline stages are application services with external adapters.
- ADR 005: Test taxonomy distinguishes unit, integration, adapter contract, fake-backed UI, and true product E2E.
- ADR 006: Open-source runtime must provide deterministic setup, dependency checks, and clear failure diagnostics.

## Final Assessment

This codebase should not be treated as unrecoverable. It should be treated as a promising POC that crossed the threshold into product work before the architecture boundary was made explicit.

The product should not be rebuilt from scratch yet. The better strategy is to establish architectural policy, add tests that enforce that policy, and migrate one runtime stage at a time into product-owned services. The highest-leverage move is to stop the POC dependency from spreading, then remove it methodically.

The target is not a microservice system. It is a disciplined modular monolith: one product, one database source of truth, one workflow state machine, explicit adapters for heavyweight tools, and tests that make architecture regressions hard to introduce.
