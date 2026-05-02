import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import PipelinePanel from "./PipelinePanel";
import type { BackendWorkflowStage, Scene, SongDetail, StageStatus, WorkflowActionState } from "../types";
import type { RegenRunSummary } from "../api";

function transcribeRun(overrides: Partial<RegenRunSummary> = {}): RegenRunSummary {
  return {
    id: 1, scope: "stage_audio_transcribe", song_id: 1, scene_id: null,
    scene_index: null, artefact_kind: null, status: "running",
    quality_mode: null, cost_estimate_usd: null, started_at: 1, ended_at: null,
    error: null, progress_pct: null, phase: null, created_at: 1,
    ...overrides,
  };
}

function makeSong(partial: Partial<SongDetail> = {}): SongDetail {
  return {
    slug: "tiny", audio_path: "/x.wav", duration_s: 5, size_bytes: 1,
    filter: "charcoal", abstraction: 25, quality_mode: "draft",
    world_brief: "w", sequence_arc: "a", scenes: [],
    ...partial,
  };
}

function makeScene(partial: Partial<Scene> = {}): Scene {
  return {
    index: 0,
    kind: "lyric",
    target_text: "a",
    start_s: 0,
    end_s: 1,
    target_duration_s: 1,
    num_frames: 24,
    beat: "b",
    camera_intent: null,
    subject_focus: null,
    prev_link: null,
    next_link: null,
    image_prompt: "p",
    prompt_is_user_authored: false,
    selected_keyframe_path: null,
    selected_clip_path: null,
    missing_assets: [],
    dirty_flags: [],
    ...partial,
  };
}

function status(overrides: Partial<StageStatus> = {}): StageStatus {
  return {
    transcription: "done", world_brief: "done", storyboard: "done",
    keyframes_done: 2, keyframes_total: 2, clips_done: 0, clips_total: 2,
    final: "empty", ...overrides,
  };
}

function backendStage(
  key: string,
  label: string,
  state: WorkflowActionState,
  overrides: Partial<BackendWorkflowStage> = {},
): BackendWorkflowStage {
  const scope = key === "final_video" ? "final_video" : `stage_${key}`;
  return {
    key,
    label,
    stage_name: key.replace("_", "-"),
    scope,
    history_model: key === "keyframes" ? "take" : "replace",
    state,
    done: state === "done",
    available: !["blocked", "running"].includes(state),
    can_start: ["available", "done", "stale"].includes(state),
    can_retry: state === "retryable",
    blocked_reason: state === "blocked" ? "Blocked by backend" : null,
    failed_reason: null,
    stale_reasons: [],
    invalidates: [],
    summary: "",
    active_run: null,
    failed_run: null,
    progress: null,
    ...overrides,
  };
}

function backendWorkflow(overrides: Partial<Record<string, Partial<BackendWorkflowStage>>> = {}) {
  const base = {
    transcription: backendStage("transcription", "transcription", "done", { scope: "stage_audio_transcribe", stage_name: "transcribe" }),
    world_brief: backendStage("world_brief", "world description", "done", { stage_name: "world-brief" }),
    storyboard: backendStage("storyboard", "storyboard", "done"),
    image_prompts: backendStage("image_prompts", "image prompts", "done", { stage_name: "image-prompts", summary: " (1/1)" }),
    keyframes: backendStage("keyframes", "keyframes", "done", { summary: " (1/1)" }),
    final_video: backendStage("final_video", "final video", "available", { stage_name: "render-final", scope: "final_video" }),
  };
  for (const [key, value] of Object.entries(overrides)) {
    base[key as keyof typeof base] = { ...base[key as keyof typeof base], ...value };
  }
  return { stages: base };
}

describe("PipelinePanel", () => {
  it("renders 6 breadcrumb segments and shows 'done' for completed ones", () => {
    const { container } = render(<PipelinePanel song={makeSong()} status={status()} />);
    expect(screen.getByText(/transcription/)).toBeInTheDocument();
    expect(screen.getByText(/world description/)).toBeInTheDocument();
    expect(screen.getByText(/storyboard/)).toBeInTheDocument();
    expect(screen.getByText(/image prompts/)).toBeInTheDocument();
    expect(screen.getByText(/keyframes \(2\/2\)/)).toBeInTheDocument();
    expect(screen.getByText(/final video/)).toBeInTheDocument();
    // Breadcrumb wraps everything — exactly 6 segments.
    expect(container.querySelectorAll(".pipeline-stage")).toHaveLength(6);
    // 5 chevrons between 6 segments.
    expect(container.querySelectorAll(".pipeline-chevron")).toHaveLength(5);
  });

  it("shows progress class when keyframes partial", () => {
    const { container } = render(
      <PipelinePanel song={makeSong()} status={status({ keyframes_done: 1, keyframes_total: 5 })} />,
    );
    const kf = Array.from(container.querySelectorAll(".pipeline-stage"))
      .find(el => el.textContent?.includes("keyframes (1/5)"))!;
    expect(kf).toHaveClass("progress");
  });

  it("done world-brief opens the world-description edit-or-regen modal, regenerate confirms and POSTs", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 1, status: "pending" }),
    } as Response);
    globalThis.fetch = fetchSpy;

    render(<PipelinePanel song={makeSong()} status={status()} />);
    const runBtn = screen.getByText(/world description/).closest("button")!;
    await userEvent.click(runBtn);
    // First modal: editable world description.
    expect(screen.getByRole("heading", { name: /World description for/ })).toBeInTheDocument();
    // Regenerate button opens the "big deal" nested confirmation.
    const regenBtn = screen.getByRole("button", { name: /^Regenerate$/ });
    await userEvent.click(regenBtn);
    expect(screen.getByRole("heading", { name: /This is a big deal/ })).toBeInTheDocument();
    // Inside the confirmation, click the (second) Regenerate button.
    const confirmBtn = screen.getAllByRole("button", { name: /^Regenerate$/ }).at(-1)!;
    await userEvent.click(confirmBtn);

    await new Promise(r => setTimeout(r, 10));
    const urls = fetchSpy.mock.calls.map(c => c[0] as string);
    const stageCall = urls.find(u => u.includes("/stages/world-brief"));
    expect(stageCall).toBeDefined();
    expect(stageCall!).toContain("redo=true");
  });

  it("world-description modal: editing and saving PATCHes /api/songs/:slug", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ ...makeSong(), world_brief: "edited" }),
    } as Response);
    globalThis.fetch = fetchSpy;

    render(<PipelinePanel song={makeSong()} status={status()} onSongUpdate={() => {}} />);
    await userEvent.click(screen.getByText(/world description/).closest("button")!);
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    await userEvent.tripleClick(textarea);
    await userEvent.keyboard("edited");
    const saveBtn = screen.getByRole("button", { name: /Save edit/i });
    await userEvent.click(saveBtn);
    await new Promise(r => setTimeout(r, 10));
    const patchCall = fetchSpy.mock.calls.find(c =>
      (c[1] as RequestInit)?.method === "PATCH"
      && String(c[0]).includes("/api/songs/tiny"),
    );
    expect(patchCall).toBeDefined();
    expect(JSON.parse((patchCall![1] as RequestInit).body as string))
      .toEqual({ world_brief: "edited" });
  });

  it("transcribe row shows spinner when an active transcribe run exists", () => {
    const song = makeSong({ duration_s: 180 });
    render(
      <PipelinePanel
        song={song}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({ status: "running", started_at: null })]}
      />,
    );
    const row = screen.getByText(/transcription/).closest(".pipeline-stage")!;
    expect(row).toHaveClass("running");
    expect(row.textContent).toContain("Preparing");
    // Run button is disabled (showing the ellipsis) so the user can't double-click.
    const btn = row.querySelector("button")!;
    expect(btn).toBeDisabled();
  });

  it("transcribe row shows failed banner + Try again when latest transcribe run failed", () => {
    const { rerender } = render(
      <PipelinePanel
        song={makeSong()}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({ id: 7, status: "running" })]}
      />,
    );
    rerender(
      <PipelinePanel
        song={makeSong()}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({
          id: 7,
          status: "failed",
          error: "expected music/no-mans-land.txt to exist",
          ended_at: 100,
        })]}
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "expected music/no-mans-land.txt to exist",
    );
    expect(screen.getByRole("button", { name: /Try again/i })).toBeInTheDocument();
  });

  it("Try again button POSTs /audio-transcribe with force=true", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 2, status: "pending" }),
    } as Response);
    globalThis.fetch = fetchSpy;

    const { rerender } = render(
      <PipelinePanel
        song={makeSong()}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({ id: 7, status: "running" })]}
      />,
    );
    rerender(
      <PipelinePanel
        song={makeSong()}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({ id: 7, status: "failed", error: "boom", ended_at: 1 })]}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Try again/i }));
    await new Promise(r => setTimeout(r, 10));
    const transcribeCall = fetchSpy.mock.calls
      .map(c => c[0] as string)
      .find(u => u.includes("/audio-transcribe"));
    expect(transcribeCall).toBeDefined();
    expect(transcribeCall!).toContain("force=true");
  });

  it("Try again optimistically dismisses the failed banner before the next poll", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 99, status: "pending" }),
    } as Response);
    globalThis.fetch = fetchSpy;

    const { rerender } = render(
      <PipelinePanel
        song={makeSong()}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({ id: 7, status: "running" })]}
      />,
    );
    rerender(
      <PipelinePanel
        song={makeSong()}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({ id: 7, status: "failed", error: "preflight failed", ended_at: 1 })]}
      />,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Try again/i }));
    await new Promise(r => setTimeout(r, 10));
    // The same regenRuns prop is still passed (next SWR poll hasn't fired)
    // but the banner must dismiss immediately so the user doesn't see the
    // old error linger.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("transcribe progress shows processed audio time when present", () => {
    const fixedNowMs = 1_700_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(fixedNowMs);
    const startedAt = fixedNowMs / 1000 - 3;
    render(
      <PipelinePanel
        song={makeSong()}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({
          status: "running", started_at: startedAt, progress_pct: 10, phase: "transcribing",
        })]}
      />,
    );
    const row = screen.getByText(/transcription/).closest(".pipeline-stage")!;
    expect(row.textContent).toContain("Transcribing");
    expect(row.textContent).toContain("processed");
  });

  it("active transcribe run wins over a stale failed one (no banner during retry)", () => {
    render(
      <PipelinePanel
        song={makeSong()}
        status={status({ transcription: "empty" })}
        regenRuns={[
          transcribeRun({ id: 9, status: "running", started_at: 1 }),
          transcribeRun({ id: 7, status: "failed", error: "earlier failure", ended_at: 1, created_at: 0 }),
        ]}
      />,
    );
    // Spinner is visible…
    const row = screen.getByText(/transcription/).closest(".pipeline-stage")!;
    expect(row).toHaveClass("running");
    // …and the failed banner is NOT — even though a failed run exists.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("latest cancelled transcribe run suppresses older failed banner", () => {
    render(
      <PipelinePanel
        song={makeSong({ scenes: [] })}
        status={status({ transcription: "empty" })}
        regenRuns={[
          transcribeRun({
            id: 8, status: "cancelled", error: null, ended_at: 2, created_at: 2,
            scope: "stage_audio_transcribe",
          }),
          transcribeRun({
            id: 7, status: "failed", error: "old demucs failure", ended_at: 1,
            created_at: 1, scope: "stage_audio_transcribe",
          }),
        ]}
      />,
    );

    expect(screen.queryByText(/old demucs failure/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Transcribe from audio/i })).toBeInTheDocument();
  });

  // Skipped: progress_pct-based ETA test from task body case 1 is parked
  // until regen_runs gets a progress_pct column (task 12.4 follow-up).
  // The heuristic-fallback ETA is covered by the "spinner + ETA" test
  // above — that exercises the only ETA path that currently exists.

  it("each segment carries data-status reflecting its traffic-light state", () => {
    const { container } = render(
      <PipelinePanel
        song={makeSong()}
        status={status({
          transcription: "done", world_brief: "done", storyboard: "empty",
          keyframes_done: 0, keyframes_total: 2,
        })}
      />,
    );
    const get = (key: string) =>
      container.querySelector(`[data-stage="${key}"]`)!.getAttribute("data-status");
    expect(get("transcription")).toBe("done");
    expect(get("world_brief")).toBe("done");
    expect(get("storyboard")).toBe("pending");
    // image_prompts/keyframes/final_video are blocked because storyboard isn't done.
    expect(get("image_prompts")).toBe("blocked");
    expect(get("keyframes")).toBe("blocked");
    expect(get("final_video")).toBe("blocked");
  });

  it("traffic-light glyph + label backups render alongside the colour for accessibility", () => {
    const { container } = render(
      <PipelinePanel song={makeSong()} status={status()} />,
    );
    // Done stages carry the ✓ glyph and an accessible status label backup.
    const transcribe = container.querySelector('[data-stage="transcription"]')!;
    expect(transcribe.querySelector(".stage-indicator--done")).not.toBeNull();
    expect(transcribe.querySelector(".stage-indicator-glyph")?.textContent).toBe("✓");
    const statusLabel = transcribe.querySelector(".stage-status-label");
    expect(statusLabel?.textContent).toBe("done");
    expect(statusLabel).toHaveClass("sr-only");
  });

  it("clicking a blocked segment opens a tooltip naming the prereq", async () => {
    const { container } = render(
      <PipelinePanel
        song={makeSong()}
        status={status({
          transcription: "empty", world_brief: "empty", storyboard: "empty",
          keyframes_done: 0, keyframes_total: 2,
        })}
      />,
    );
    // Storyboard is blocked because world_brief is empty (and transcription
    // is empty, but with empty scenes too).
    const storyboardBtn = container.querySelector(
      '[data-stage="storyboard"] button',
    ) as HTMLButtonElement;
    await userEvent.click(storyboardBtn);
    const tooltip = container.querySelector(".pipeline-tooltip");
    expect(tooltip).not.toBeNull();
    expect(tooltip!.textContent).toMatch(/world description/i);
  });

  it("clicking a done image-prompts segment opens a regen-confirmation modal", async () => {
    render(
      <PipelinePanel
        song={makeSong({
          scenes: [makeScene()],
        })}
        status={status()}
      />,
    );
    const imgPromptsBtn = screen.getByText(/image prompts/).closest("button")!;
    await userEvent.click(imgPromptsBtn);
    expect(
      screen.getByRole("heading", { name: /Regenerate image prompts\?/i }),
    ).toBeInTheDocument();
    // Replace-history copy: mentions "replace the existing".
    expect(document.body.textContent).toMatch(/replace the existing image prompts/i);
  });

  it("clicking a done keyframes segment surfaces the take-history copy", async () => {
    render(
      <PipelinePanel
        song={makeSong()}
        status={status({ keyframes_done: 2, keyframes_total: 2 })}
      />,
    );
    const kfBtn = screen.getByText(/keyframes/).closest("button")!;
    await userEvent.click(kfBtn);
    expect(
      screen.getByRole("heading", { name: /Regenerate keyframes\?/i }),
    ).toBeInTheDocument();
    // Take-history copy: mentions "creates a new take" not "replace the existing".
    expect(document.body.textContent).toMatch(/creates a new take/i);
  });

  // ---- Story 14 — audio-transcribe surfaces ----

  it("Story 14: Transcribe-from-audio button appears when transcription is pending and no scenes", () => {
    render(
      <PipelinePanel
        song={makeSong({ scenes: [] })}
        status={status({ transcription: "empty" })}
      />,
    );
    expect(
      screen.getByRole("button", { name: /Transcribe from audio/i }),
    ).toBeInTheDocument();
  });

  it("Story 14: Transcribe-from-audio button hidden when an audio-transcribe run is in flight", () => {
    render(
      <PipelinePanel
        song={makeSong({ scenes: [] })}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({ scope: "stage_audio_transcribe", status: "running" })]}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /Transcribe from audio/i }),
    ).not.toBeInTheDocument();
  });

  it("Story 14: clicking Transcribe-from-audio opens the first-run confirm modal", async () => {
    render(
      <PipelinePanel
        song={makeSong({ scenes: [] })}
        status={status({ transcription: "empty" })}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Transcribe from audio/i }),
    );
    expect(screen.getByRole("heading", { name: /Transcribe from audio/i })).toBeInTheDocument();
    expect(document.body.textContent).toMatch(/separates the vocals/i);
    expect(screen.getByRole("button", { name: /^Start$/ })).toBeInTheDocument();
  });

  it("Story 14: Start fires POST /audio-transcribe with force=false", async () => {
    const fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/audio-transcribe")) {
        return {
          ok: true, status: 200, json: async () => ({ run_id: 5, status: "pending" }),
        } as Response;
      }
      return { ok: true, status: 200, json: async () => ({ finished: [] }) } as Response;
    });
    globalThis.fetch = fetchSpy;
    render(
      <PipelinePanel
        song={makeSong({ scenes: [] })}
        status={status({ transcription: "empty" })}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Transcribe from audio/i }));
    await userEvent.click(screen.getByRole("button", { name: /^Start$/ }));
    await new Promise(r => setTimeout(r, 10));
    const url = fetchSpy.mock.calls.map(c => c[0] as string)
      .find(u => u.includes("/audio-transcribe"));
    expect(url).toBeDefined();
    expect(url!).toContain("force=false");
  });

  it("Story 14: 409 overwrite_required flips the modal to overwrite copy + force=true on confirm", async () => {
    let audioTranscribeCalls = 0;
    const fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/audio-transcribe")) {
        audioTranscribeCalls += 1;
        if (audioTranscribeCalls === 1) {
          return {
            ok: false, status: 409,
            // FastAPI envelopes HTTPException(detail=...) under {"detail": ...}.
            json: async () => ({ detail: { code: "overwrite_required" } }),
          } as Response;
        }
        return {
          ok: true, status: 200,
          json: async () => ({ run_id: 5, status: "pending" }),
        } as Response;
      }
      // /finished poll on mount + any other request → empty success.
      return {
        ok: true, status: 200, json: async () => ({ finished: [] }),
      } as Response;
    });
    globalThis.fetch = fetchSpy;
    render(
      <PipelinePanel
        song={makeSong({ scenes: [] })}
        status={status({ transcription: "empty" })}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Transcribe from audio/i }));
    await userEvent.click(screen.getByRole("button", { name: /^Start$/ }));
    await new Promise(r => setTimeout(r, 10));
    expect(document.body.textContent).toMatch(/already exists/i);
    await userEvent.click(screen.getByRole("button", { name: /^Overwrite$/ }));
    await new Promise(r => setTimeout(r, 10));
    const calls = fetchSpy.mock.calls.map(c => c[0] as string);
    expect(calls.some(u => u.includes("/audio-transcribe") && u.includes("force=true"))).toBe(true);
  });

  it("Story 14: phase label 'Separating vocals…' renders for stage_audio_transcribe running run", () => {
    render(
      <PipelinePanel
        song={makeSong({ scenes: [] })}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({
          scope: "stage_audio_transcribe", status: "running",
          phase: "separating-vocals",
        })]}
      />,
    );
    expect(document.body.textContent).toMatch(/Separating vocals/);
  });

  it("Story 14: phase label 'Transcribing…' renders during the WhisperX phase", () => {
    render(
      <PipelinePanel
        song={makeSong({ scenes: [] })}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({
          scope: "stage_audio_transcribe", status: "running",
          phase: "transcribing",
        })]}
      />,
    );
    expect(document.body.textContent).toMatch(/^.*Transcribing.*$/);
  });

  it("Story 21: audio transcription shows processed time against total duration", () => {
    render(
      <PipelinePanel
        song={makeSong({ scenes: [], duration_s: 228 })}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({
          scope: "stage_audio_transcribe", status: "running",
          phase: "transcribing", progress_pct: 50,
        })]}
      />,
    );
    expect(document.body.textContent).toContain("Transcribing · 1:54 / 3:48 processed");
  });

  it("Story 21: stage status words are visually hidden rather than shown in pills", () => {
    const { container } = render(
      <PipelinePanel
        song={makeSong({ scenes: [] })}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({ scope: "stage_audio_transcribe", status: "running" })]}
      />,
    );
    const label = container.querySelector('[data-stage="transcription"] .stage-status-label');
    expect(label).toHaveClass("sr-only");
    expect(container.querySelector('[data-stage="transcription"] .stage-indicator'))
      ?.toHaveAttribute("aria-label", "running");
  });

  it("Story 14: phase=null renders preparing copy", () => {
    render(
      <PipelinePanel
        song={makeSong({ scenes: [], duration_s: 60 })}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({ scope: "stage_audio_transcribe", status: "running" })]}
      />,
    );
    expect(document.body.textContent).toContain("Preparing");
  });

  it("Story 14: failed audio-transcribe Try-again calls audioTranscribe with force=true", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 7, status: "pending" }),
    } as Response);
    globalThis.fetch = fetchSpy;
    const { rerender } = render(
      <PipelinePanel
        song={makeSong({ scenes: [] })}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({ id: 7, scope: "stage_audio_transcribe", status: "running" })]}
      />,
    );
    rerender(
      <PipelinePanel
        song={makeSong({ scenes: [] })}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({
          id: 7,
          scope: "stage_audio_transcribe", status: "failed",
          error: "demucs blew up", ended_at: 1,
        })]}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Try again/i }));
    await new Promise(r => setTimeout(r, 10));
    const url = fetchSpy.mock.calls.map(c => c[0] as string)
      .find(u => u.includes("/audio-transcribe"));
    expect(url).toBeDefined();
    expect(url!).toContain("force=true");
  });

  it("POSTs without confirm for a stage not yet done", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 1, status: "pending" }),
    } as Response);
    globalThis.fetch = fetchSpy;

    render(<PipelinePanel song={makeSong()} status={status({
      transcription: "done", world_brief: "empty", storyboard: "empty",
      keyframes_done: 0, keyframes_total: 2,
    })} />);
    await userEvent.click(screen.getByText(/world description/).closest("button")!);
    await new Promise(r => setTimeout(r, 10));
    expect(fetchSpy).toHaveBeenCalled();
    const urls = fetchSpy.mock.calls.map(c => c[0] as string);
    const stageCall = urls.find(u => u.includes("/stages/world-brief"));
    expect(stageCall).toBeDefined();
    expect(stageCall!).toContain("redo=false");
  });

  it("world generation that fails immediately shows retry state, retry icon, and error fallback", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 4, status: "pending" }),
    } as Response);
    globalThis.fetch = fetchSpy;
    const pendingSong = makeSong({
      world_brief: null,
      sequence_arc: null,
      scenes: [makeScene()],
    });
    const pendingStatus = status({
      transcription: "done", world_brief: "empty", storyboard: "empty",
      keyframes_done: 0, keyframes_total: 1,
    });
    const { container, rerender } = render(
      <PipelinePanel song={pendingSong} status={pendingStatus} />,
    );

    await userEvent.click(screen.getByText(/world description/).closest("button")!);
    await new Promise(r => setTimeout(r, 10));
    expect(fetchSpy.mock.calls.some(c => String(c[0]).includes("/stages/world-brief"))).toBe(true);

    rerender(
      <PipelinePanel
        song={pendingSong}
        status={pendingStatus}
        regenRuns={[transcribeRun({
          id: 4,
          scope: "stage_world_brief",
          status: "failed",
          error: null,
          ended_at: 2,
        })]}
      />,
    );

    const world = container.querySelector('[data-stage="world_brief"]')!;
    expect(world).toHaveAttribute("data-status", "failed");
    expect(world.querySelector(".stage-indicator-glyph")?.textContent).toBe("⟳");
    expect(screen.getByRole("alert").textContent).toContain("world description failed. Try again.");

    await userEvent.click(screen.getByRole("button", { name: /Try again/i }));
    await new Promise(r => setTimeout(r, 10));
    const retryCall = fetchSpy.mock.calls
      .map(c => String(c[0]))
      .filter(url => url.includes("/stages/world-brief"))
      .at(-1);
    expect(retryCall).toContain("redo=true");
  });

  it("does not show a previous world-generation failure as the current page result", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 45, status: "pending" }),
    } as Response);
    globalThis.fetch = fetchSpy;
    const previousError = "Generation provider returned no world description.";
    const song = makeSong({
      world_brief: null,
      sequence_arc: null,
      scenes: [makeScene()],
      workflow: backendWorkflow({
        world_brief: {
          state: "retryable",
          done: false,
          can_retry: true,
          failed_reason: previousError,
          failed_run: {
            id: 44,
            scope: "stage_world_brief",
            status: "failed",
            error: previousError,
            progress_pct: null,
            phase: null,
            started_at: 1,
            ended_at: 2,
            created_at: 2,
          },
        },
        storyboard: {
          state: "blocked",
          done: false,
          available: false,
          can_start: false,
          blocked_reason: "Complete world description first.",
        },
      }),
    });
    const { container } = render(<PipelinePanel
      song={song}
      status={status({
        transcription: "done", world_brief: "empty", storyboard: "empty",
        keyframes_done: 0, keyframes_total: 1,
      })}
    />);

    const world = container.querySelector('[data-stage="world_brief"]')!;
    expect(world).toHaveAttribute("data-status", "pending");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(previousError)).not.toBeInTheDocument();

    await userEvent.click(world.querySelector("button")!);
    await new Promise(r => setTimeout(r, 10));
    const retryCall = fetchSpy.mock.calls
      .map(c => String(c[0]))
      .find(url => url.includes("/stages/world-brief"));
    expect(retryCall).toContain("redo=true");
  });

  it("setup picker uses approved filter descriptions and abstraction defaults to 0", async () => {
    render(<PipelinePanel
      song={makeSong({ filter: null, abstraction: null, world_brief: null, scenes: [makeScene()] })}
      status={status({
        transcription: "done", world_brief: "empty", storyboard: "empty",
        keyframes_done: 0, keyframes_total: 1,
      })}
    />);
    await userEvent.click(screen.getByText(/world description/).closest("button")!);

    expect(screen.getByRole("heading", { name: /Choose the visual language/i })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getAllByText(/Thick palette-knife paint/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Layered cut-paper diorama/i).length).toBeGreaterThan(0);
    const selects = screen.getAllByRole("combobox") as HTMLSelectElement[];
    expect(selects[1]!.value).toBe("0");
    expect(screen.getByText(/Concrete, recognisable scenes/i)).toBeInTheDocument();
  });

  it("blocked world visual-language setup opens picker instead of tooltip", async () => {
    const song = makeSong({
      filter: null,
      abstraction: null,
      world_brief: null,
      scenes: [makeScene()],
      workflow: backendWorkflow({
        world_brief: {
          state: "blocked",
          done: false,
          available: false,
          can_start: false,
          blocked_reason: "Choose a filter and abstraction first.",
        },
      }),
    });
    render(<PipelinePanel song={song} status={status({
      transcription: "done", world_brief: "empty", storyboard: "empty",
      keyframes_done: 0, keyframes_total: 1,
    })} />);

    await userEvent.click(screen.getByText(/world description/).closest("button")!);

    expect(screen.getByRole("heading", { name: /Choose the visual language/i })).toBeInTheDocument();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("visual-language setup patches both values and does not separately POST the world stage", async () => {
    const updated = makeSong({ filter: "cyanotype", abstraction: 0, world_brief: null, scenes: [makeScene()] });
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => updated,
    } as Response);
    globalThis.fetch = fetchSpy;
    const onSongUpdate = vi.fn();

    render(<PipelinePanel
      song={makeSong({ filter: null, abstraction: null, world_brief: null, scenes: [makeScene()] })}
      status={status({
        transcription: "done", world_brief: "empty", storyboard: "empty",
        keyframes_done: 0, keyframes_total: 1,
      })}
      onSongUpdate={onSongUpdate}
    />);

    await userEvent.click(screen.getByText(/world description/).closest("button")!);
    await userEvent.selectOptions(screen.getAllByRole("combobox")[0] as HTMLSelectElement, "cyanotype");
    await userEvent.click(screen.getByRole("button", { name: /Confirm and run/i }));

    await new Promise(r => setTimeout(r, 10));
    const calls = fetchSpy.mock.calls.map(([url, init]) => ({ url: String(url), init: init as RequestInit | undefined }));
    const patchCalls = calls.filter(call => call.url === "/api/songs/tiny");
    expect(patchCalls).toHaveLength(1);
    expect(JSON.parse(String(patchCalls[0]!.init?.body))).toEqual({ filter: "cyanotype", abstraction: 0 });
    expect(calls.some(call => call.url.includes("/stages/world-brief"))).toBe(false);
    expect(onSongUpdate).toHaveBeenCalledWith(updated);
  });

  it("visual-language setup reports saved blocked workflow without raw HTTP error text", async () => {
    const updated = makeSong({
      filter: "charcoal",
      abstraction: 0,
      world_brief: null,
      scenes: [makeScene()],
      workflow: backendWorkflow({
        world_brief: {
          state: "blocked",
          blocked_reason: "generation requires GEMINI_API_KEY or a configured product generation provider before it can start.",
        },
      }),
    });
    const fetchSpy = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/songs/tiny" && init?.method === "PATCH") {
        return {
          ok: true,
          status: 200,
          json: async () => updated,
        } as Response;
      }
      if (url === "/api/songs/tiny") {
        return {
          ok: true,
          status: 200,
          json: async () => updated,
        } as Response;
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ finished: [] }),
      } as Response;
    });
    globalThis.fetch = fetchSpy;
    const onSongUpdate = vi.fn();

    render(<PipelinePanel
      song={makeSong({ filter: null, abstraction: null, world_brief: null, scenes: [makeScene()] })}
      status={status({
        transcription: "done", world_brief: "empty", storyboard: "empty",
        keyframes_done: 0, keyframes_total: 1,
      })}
      onSongUpdate={onSongUpdate}
    />);

    await userEvent.click(screen.getByText(/world description/).closest("button")!);
    await userEvent.click(screen.getByRole("button", { name: /Confirm and run/i }));

    await waitFor(() => expect(onSongUpdate).toHaveBeenCalledWith(updated));
    expect(screen.queryByText(/HTTP 422/i)).not.toBeInTheDocument();
    expect(screen.getByText(/generation requires GEMINI_API_KEY/i)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("existing world exposes confirmed visual-language change from the world dialog", async () => {
    render(<PipelinePanel song={makeSong()} status={status()} />);

    await userEvent.click(screen.getByText(/world description/).closest("button")!);
    await userEvent.click(screen.getByRole("button", { name: /Change visual language/i }));

    expect(screen.getByRole("heading", { name: /Change the visual language/i })).toBeInTheDocument();
    expect(screen.getByText(/regenerates the world description, storyboard, scene prompts, and keyframes/i))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Apply and regenerate/i })).toBeDisabled();
  });

  it("Story 29: renders blocked reason from backend workflow state", async () => {
    const song = makeSong({
      workflow: backendWorkflow({
        keyframes: {
          state: "blocked",
          done: false,
          available: false,
          can_start: false,
          blocked_reason: "Please generate the world and storyboard first.",
          summary: " (0/1)",
        },
      }),
    });
    const { container } = render(
      <PipelinePanel song={song} status={status({ keyframes_done: 0, keyframes_total: 1 })} />,
    );

    const keyframes = container.querySelector('[data-stage="keyframes"]')!;
    expect(keyframes).toHaveAttribute("data-status", "blocked");
    await userEvent.click(keyframes.querySelector("button")!);
    expect(screen.getByRole("tooltip").textContent).toContain(
      "Please generate the world and storyboard first.",
    );
  });

  it("Story 29: renders operation-specific backend progress without mixed labels", () => {
    const song = makeSong({
      duration_s: 228,
      workflow: backendWorkflow({
        transcription: {
          state: "running",
          done: false,
          active_run: {
            id: 42,
            scope: "stage_audio_transcribe",
            status: "running",
            error: null,
            progress_pct: 50,
            phase: "transcribing",
            started_at: 1,
            ended_at: null,
            created_at: 1,
          },
          progress: {
            operation: "Transcribing",
            detail: "audio time processed",
            progress_pct: 50,
            processed_seconds: 114,
            total_seconds: 228,
          },
        },
      }),
    });
    render(<PipelinePanel song={song} status={status()} />);

    expect(document.body.textContent).toContain("Transcribing · 1:54 / 3:48 processed");
    expect(document.body.textContent).not.toContain("Aligning lyrics");
  });

  it("Story 29: stale backend actions show the stale reason and remain actionable", () => {
    const song = makeSong({
      workflow: backendWorkflow({
        keyframes: {
          state: "stale",
          done: false,
          stale_reasons: ["Scene prompts changed; regenerate stale keyframes."],
          summary: " (1/1)",
        },
      }),
    });
    const { container } = render(<PipelinePanel song={song} status={status()} />);

    const keyframes = container.querySelector('[data-stage="keyframes"]')!;
    expect(keyframes).toHaveAttribute("data-status", "pending");
    expect(keyframes.textContent).toContain("Scene prompts changed; regenerate stale keyframes.");
    expect(keyframes.querySelector("button")).not.toBeDisabled();
  });
});

afterEach(() => vi.restoreAllMocks());
