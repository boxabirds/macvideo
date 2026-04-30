import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import PipelinePanel from "./PipelinePanel";
import type { Scene, SongDetail, StageStatus } from "../types";
import type { RegenRunSummary } from "../api";

function transcribeRun(overrides: Partial<RegenRunSummary> = {}): RegenRunSummary {
  return {
    id: 1, scope: "stage_transcribe", song_id: 1, scene_id: null,
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

describe("PipelinePanel", () => {
  it("renders 6 breadcrumb segments and shows 'done' for completed ones", () => {
    const { container } = render(<PipelinePanel song={makeSong()} status={status()} />);
    expect(screen.getByText(/lyric alignment/)).toBeInTheDocument();
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

  it("transcribe row shows spinner + ETA when an active transcribe run exists", () => {
    const song = makeSong({ duration_s: 180 });  // 180s × 0.5 = 90s ETA
    render(
      <PipelinePanel
        song={song}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({ status: "running" })]}
      />,
    );
    const row = screen.getByText(/lyric alignment/).closest(".pipeline-stage")!;
    expect(row).toHaveClass("running");
    expect(row.textContent).toContain("about 90 seconds left");
    // Run button is disabled (showing the ellipsis) so the user can't double-click.
    const btn = row.querySelector("button")!;
    expect(btn).toBeDisabled();
  });

  it("transcribe row shows failed banner + Try again when latest transcribe run failed", () => {
    render(
      <PipelinePanel
        song={makeSong()}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({
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

  it("does not render obsolete POC usage stderr as the current transcribe failure", () => {
    render(
      <PipelinePanel
        song={makeSong()}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({
          status: "failed",
          error: "Audio transcription failed in an older build. Try again to run the current product transcription pipeline.",
          ended_at: 100,
        })]}
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "current product transcription pipeline",
    );
    expect(document.body.textContent).not.toContain("pocs/30-whisper-timestamped");
    expect(document.body.textContent).not.toContain("transcribe_whisperx_noprompt.py");
  });

  it("Try again button POSTs /stages/transcribe with redo=true", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 2, status: "pending" }),
    } as Response);
    globalThis.fetch = fetchSpy;

    render(
      <PipelinePanel
        song={makeSong()}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({ status: "failed", error: "boom", ended_at: 1 })]}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Try again/i }));
    await new Promise(r => setTimeout(r, 10));
    const stageCall = fetchSpy.mock.calls
      .map(c => c[0] as string)
      .find(u => u.includes("/stages/transcribe"));
    expect(stageCall).toBeDefined();
    expect(stageCall!).toContain("redo=true");
  });

  it("Try again optimistically dismisses the failed banner before the next poll", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 99, status: "pending" }),
    } as Response);
    globalThis.fetch = fetchSpy;

    render(
      <PipelinePanel
        song={makeSong()}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({
          id: 7, status: "failed", error: "preflight failed", ended_at: 1,
        })]}
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

  it("transcribe ETA uses progress_pct + started_at when present", () => {
    // pct=10, elapsed=3s → totalEstimated = 30s, remaining = 27s → round to 25s.
    const fixedNowMs = 1_700_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(fixedNowMs);
    const startedAt = fixedNowMs / 1000 - 3;
    render(
      <PipelinePanel
        song={makeSong()}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({
          status: "running", started_at: startedAt, progress_pct: 10,
        })]}
      />,
    );
    const row = screen.getByText(/lyric alignment/).closest(".pipeline-stage")!;
    expect(row.textContent).toContain("about 25 seconds left");
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
    const row = screen.getByText(/lyric alignment/).closest(".pipeline-stage")!;
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
    // Done stages carry the ✓ glyph and the 'done' status label.
    const transcribe = container.querySelector('[data-stage="transcription"]')!;
    expect(transcribe.querySelector(".stage-indicator--done")).not.toBeNull();
    expect(transcribe.querySelector(".stage-indicator-glyph")?.textContent).toBe("✓");
    expect(transcribe.querySelector(".stage-status-label")?.textContent).toBe("done");
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
    expect(document.body.textContent).toMatch(/Separating vocals…/);
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
    expect(document.body.textContent).toMatch(/^.*Transcribing….*$/);
  });

  it("Story 14: phase=null falls back to Story 12 ETA copy", () => {
    render(
      <PipelinePanel
        song={makeSong({ scenes: [], duration_s: 60 })}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({ scope: "stage_transcribe", status: "running" })]}
      />,
    );
    expect(document.body.textContent).toMatch(/about \d+ seconds left/);
  });

  it("Story 14: failed audio-transcribe Try-again calls audioTranscribe with force=true", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 7, status: "pending" }),
    } as Response);
    globalThis.fetch = fetchSpy;
    render(
      <PipelinePanel
        song={makeSong({ scenes: [] })}
        status={status({ transcription: "empty" })}
        regenRuns={[transcribeRun({
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
});

afterEach(() => vi.restoreAllMocks());
