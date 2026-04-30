import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FilterChangeModal from "./FilterChangeModal";
import type { SongDetail } from "../types";

function makeSong(extras: Partial<SongDetail> = {}): SongDetail {
  return {
    slug: "test-song",
    audio_path: "/music/test.wav",
    duration_s: 100,
    size_bytes: 1000000,
    filter: "oil impasto",
    abstraction: 25,
    quality_mode: "draft",
    world_brief: "narrator",
    sequence_arc: "arc",
    scenes: [],
    ...extras,
  };
}

describe("FilterChangeModal", () => {
  it("renders fresh-setup modal with friendly copy", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();

    render(
      <FilterChangeModal
        song={makeSong()}
        kind="fresh-setup"
        newFilter="cyanotype"
        preview={null}
        previewError={null}
        inFlight={false}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );

    expect(screen.getByRole("heading", { name: /set filter/i })).toBeInTheDocument();
    expect(screen.getByText(/will start the pipeline/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /set filter/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /apply change/i })).not.toBeInTheDocument();
  });

  it("renders destructive modal with full cost breakdown", () => {
    const previewData = {
      from: { filter: "oil impasto", abstraction: 25 },
      to: { filter: "cyanotype", abstraction: 25 },
      scope: {
        will_regen_world_brief: true,
        will_regen_storyboard: true,
        scenes_with_new_prompts: 5,
        keyframes_to_generate: 10,
        clips_marked_stale: 8,
        clips_deleted: 0,
      },
      estimate: {
        gemini_calls: 15,
        estimated_usd: 0.75,
        estimated_seconds: 300,
        confidence: "high",
      },
      would_conflict_with: null,
    };

    render(
      <FilterChangeModal
        song={makeSong()}
        kind="destructive"
        newFilter="cyanotype"
        preview={previewData}
        previewError={null}
        inFlight={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByRole("heading", { name: /confirm filter change/i })).toBeInTheDocument();
    expect(screen.getByText(/15 Gemini calls/)).toBeInTheDocument();
    expect(screen.getByText(/\$0\.75/)).toBeInTheDocument();
    expect(screen.getByText(/5 min/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /apply change/i })).toBeInTheDocument();
  });

  it("shows loading state when preview is in flight", () => {
    render(
      <FilterChangeModal
        song={makeSong()}
        kind="destructive"
        newFilter="cyanotype"
        preview={null}
        previewError={null}
        inFlight={true}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByText(/computing estimate/)).toBeInTheDocument();
  });

  it("displays preview error when fetch fails", () => {
    render(
      <FilterChangeModal
        song={makeSong()}
        kind="destructive"
        newFilter="cyanotype"
        preview={null}
        previewError="Network error"
        inFlight={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByText(/Preview failed: Network error/)).toBeInTheDocument();
  });

  it("disables confirm button when there's a conflict", () => {
    const previewData = {
      from: { filter: "oil impasto", abstraction: 25 },
      to: { filter: "cyanotype", abstraction: 25 },
      scope: {
        will_regen_world_brief: true,
        will_regen_storyboard: true,
        scenes_with_new_prompts: 5,
        keyframes_to_generate: 10,
        clips_marked_stale: 8,
        clips_deleted: 0,
      },
      estimate: {
        gemini_calls: 15,
        estimated_usd: 0.75,
        estimated_seconds: 300,
        confidence: "high",
      },
      would_conflict_with: { run_id: 42, reason: "a chain is already running" },
    };

    render(
      <FilterChangeModal
        song={makeSong()}
        kind="destructive"
        newFilter="cyanotype"
        preview={previewData}
        previewError={null}
        inFlight={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    const confirmBtn = screen.getByRole("button", { name: /apply change/i });
    expect(confirmBtn).toBeDisabled();
    expect(screen.getByText(/run #42/)).toBeInTheDocument();
  });

  it("shows clip counts in destructive modal", () => {
    const song = makeSong({
      scenes: [
        { selected_clip_path: "/clip1.mp4" } as any,
        { selected_clip_path: "/clip2.mp4" } as any,
        { selected_clip_path: null } as any,
      ],
    });

    const previewData = {
      from: { filter: "oil impasto", abstraction: 25 },
      to: { filter: "cyanotype", abstraction: 25 },
      scope: {
        will_regen_world_brief: true,
        will_regen_storyboard: true,
        scenes_with_new_prompts: 2,
        keyframes_to_generate: 3,
        clips_marked_stale: 2,
        clips_deleted: 0,
      },
      estimate: {
        gemini_calls: 8,
        estimated_usd: 0.4,
        estimated_seconds: 180,
        confidence: "high",
      },
      would_conflict_with: null,
    };

    render(
      <FilterChangeModal
        song={song}
        kind="destructive"
        newFilter="cyanotype"
        preview={previewData}
        previewError={null}
        inFlight={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByText(/2 existing clips will be marked stale/)).toBeInTheDocument();
  });

  it("returns null when kind is noop (no modal rendered)", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();

    const { container } = render(
      <FilterChangeModal
        song={makeSong()}
        kind="noop"
        newFilter={makeSong().filter}
        preview={null}
        previewError={null}
        inFlight={false}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );

    expect(container.firstChild).toBeNull();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
  });
});
