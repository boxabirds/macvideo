import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import PipelinePanel from "./PipelinePanel";
import type { SongDetail, StageStatus } from "../types";
import type { RegenRunSummary } from "../api";

function transcribeRun(overrides: Partial<RegenRunSummary> = {}): RegenRunSummary {
  return {
    id: 1, scope: "stage_transcribe", song_id: 1, scene_id: null,
    scene_index: null, artefact_kind: null, status: "running",
    quality_mode: null, cost_estimate_usd: null, started_at: 1, ended_at: null,
    error: null, progress_pct: null, created_at: 1,
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

function status(overrides: Partial<StageStatus> = {}): StageStatus {
  return {
    transcription: "done", world_brief: "done", storyboard: "done",
    keyframes_done: 2, keyframes_total: 2, clips_done: 0, clips_total: 2,
    final: "empty", ...overrides,
  };
}

describe("PipelinePanel", () => {
  it("renders 5 stages and shows 'done' for completed ones", () => {
    render(<PipelinePanel song={makeSong()} status={status()} />);
    expect(screen.getByText(/lyric alignment/)).toBeInTheDocument();
    expect(screen.getByText(/world description/)).toBeInTheDocument();
    expect(screen.getByText(/storyboard/)).toBeInTheDocument();
    expect(screen.getByText(/image prompts/)).toBeInTheDocument();
    expect(screen.getByText(/keyframes \(2\/2\)/)).toBeInTheDocument();
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
    // @ts-expect-error
    globalThis.fetch = fetchSpy;

    render(<PipelinePanel song={makeSong()} status={status()} />);
    const worldBriefRow = screen.getByText(/world description/).parentElement!;
    const runBtn = worldBriefRow.querySelector("button")!;
    await userEvent.click(runBtn);
    // First modal: editable world description.
    expect(screen.getByRole("heading", { name: /World description for/ })).toBeInTheDocument();
    // Regenerate button opens the "big deal" nested confirmation.
    const regenBtn = screen.getByRole("button", { name: /^Regenerate$/ });
    await userEvent.click(regenBtn);
    expect(screen.getByRole("heading", { name: /This is a big deal/ })).toBeInTheDocument();
    // Inside the confirmation, click the (second) Regenerate button.
    const confirmBtns = screen.getAllByRole("button", { name: /^Regenerate$/ });
    await userEvent.click(confirmBtns[confirmBtns.length - 1]);

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
    // @ts-expect-error
    globalThis.fetch = fetchSpy;

    render(<PipelinePanel song={makeSong()} status={status()} onSongUpdate={() => {}} />);
    const worldBriefRow = screen.getByText(/world description/).parentElement!;
    await userEvent.click(worldBriefRow.querySelector("button")!);
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

  it("Try again button POSTs /stages/transcribe with redo=true", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 2, status: "pending" }),
    } as Response);
    // @ts-expect-error
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
    // @ts-expect-error
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

  // Skipped: progress_pct-based ETA test from task body case 1 is parked
  // until regen_runs gets a progress_pct column (task 12.4 follow-up).
  // The heuristic-fallback ETA is covered by the "spinner + ETA" test
  // above — that exercises the only ETA path that currently exists.

  it("POSTs without confirm for a stage not yet done", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 1, status: "pending" }),
    } as Response);
    // @ts-expect-error
    globalThis.fetch = fetchSpy;

    render(<PipelinePanel song={makeSong()} status={status({
      transcription: "done", world_brief: "empty", storyboard: "empty",
      keyframes_done: 0, keyframes_total: 2,
    })} />);
    const row = screen.getByText(/world description/).parentElement!;
    await userEvent.click(row.querySelector("button")!);
    await new Promise(r => setTimeout(r, 10));
    expect(fetchSpy).toHaveBeenCalled();
    const urls = fetchSpy.mock.calls.map(c => c[0] as string);
    const stageCall = urls.find(u => u.includes("/stages/world-brief"));
    expect(stageCall).toBeDefined();
    expect(stageCall!).toContain("redo=false");
  });
});

afterEach(() => vi.restoreAllMocks());
