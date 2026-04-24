import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
});
