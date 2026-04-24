import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import PipelinePanel from "./PipelinePanel";
import type { SongDetail, StageStatus } from "../types";

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

  it("confirms a re-run when the stage is already done, then POSTs to the stage endpoint", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 1, status: "pending" }),
    } as Response);
    // @ts-expect-error
    globalThis.fetch = fetchSpy;

    render(<PipelinePanel song={makeSong()} status={status()} />);
    // world-brief is "done", so clicking its button should open a confirm dialog.
    const worldBriefRow = screen.getByText(/world description/).parentElement!;
    const runBtn = worldBriefRow.querySelector("button")!;
    await userEvent.click(runBtn);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: /^Re-run$/i });
    await userEvent.click(confirm);

    await new Promise(r => setTimeout(r, 10));
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/api/songs/tiny/stages/world-brief"),
      expect.objectContaining({ method: "POST" }),
    );
    const urls = fetchSpy.mock.calls.map(c => c[0] as string);
    const stageCall = urls.find(u => u.includes("/stages/world-brief"));
    expect(stageCall).toBeDefined();
    expect(stageCall!).toContain("redo=true");
  });

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
