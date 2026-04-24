import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import Storyboard from "./Storyboard";
import type { Scene, SongDetail } from "../types";

function makeScene(partial: Partial<Scene> & { index: number }): Scene {
  return {
    index: partial.index,
    kind: "lyric",
    target_text: partial.target_text ?? `line ${partial.index}`,
    start_s: partial.start_s ?? partial.index,
    end_s: partial.end_s ?? (partial.index + 1),
    target_duration_s: 1,
    num_frames: 33,
    beat: partial.beat ?? "original beat",
    camera_intent: partial.camera_intent ?? "static hold",
    subject_focus: partial.subject_focus ?? "the narrator",
    prev_link: null,
    next_link: null,
    image_prompt: partial.image_prompt ?? "a prompt",
    prompt_is_user_authored: partial.prompt_is_user_authored ?? false,
    selected_keyframe_path: partial.selected_keyframe_path ?? null,
    selected_clip_path: partial.selected_clip_path ?? null,
    missing_assets: partial.missing_assets ?? [],
    dirty_flags: partial.dirty_flags ?? [],
  };
}

function makeSong(scenes: Scene[]): SongDetail {
  return {
    slug: "tiny",
    audio_path: "/music/tiny.wav",
    duration_s: 10,
    size_bytes: 1000,
    filter: "charcoal",
    abstraction: 25,
    quality_mode: "draft",
    world_brief: null,
    sequence_arc: null,
    scenes,
  };
}

function stubFetchEcho() {
  const spy = vi.fn();
  // @ts-expect-error
  globalThis.fetch = spy;
  return spy;
}

afterEach(() => vi.restoreAllMocks());

describe("Storyboard", () => {
  it("renders one scene row per scene", () => {
    const song = makeSong([makeScene({ index: 1 }), makeScene({ index: 2 })]);
    render(<Storyboard song={song} cameraIntents={["static hold", "slow push in"]}
      currentIdx={null} onSelect={() => {}} onPatch={() => {}} />);
    expect(screen.getByText("line 1")).toBeInTheDocument();
    expect(screen.getByText("line 2")).toBeInTheDocument();
  });

  it("saves on blur via PATCH and calls onPatch", async () => {
    const song = makeSong([makeScene({ index: 1, beat: "old" })]);
    const onPatch = vi.fn();
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ ...song.scenes[0], beat: "new" }),
    } as Response);
    // @ts-expect-error
    globalThis.fetch = fetchSpy;

    render(<Storyboard song={song} cameraIntents={["static hold"]}
      currentIdx={null} onSelect={() => {}} onPatch={onPatch} />);

    const beatField = screen.getByDisplayValue("old");
    await userEvent.tripleClick(beatField);
    await userEvent.keyboard("new");
    beatField.blur();
    // Wait a tick for the async patch
    await new Promise(r => setTimeout(r, 0));
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/songs/tiny/scenes/1",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("shows hand-authored indicator when prompt_is_user_authored", () => {
    const song = makeSong([
      makeScene({ index: 1, prompt_is_user_authored: true }),
    ]);
    render(<Storyboard song={song} cameraIntents={["static hold"]}
      currentIdx={null} onSelect={() => {}} onPatch={() => {}} />);
    expect(screen.getByText(/hand-authored/i)).toBeInTheDocument();
  });

  it("shows stale indicator on keyframe chip when dirty", () => {
    const song = makeSong([
      makeScene({ index: 1,
        selected_keyframe_path: "/x/keyframes/kf.png",
        dirty_flags: ["keyframe_stale"],
      }),
    ]);
    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      currentIdx={null} onSelect={() => {}} onPatch={() => {}} />);
    const kfChip = container.querySelector(".chip.kf");
    expect(kfChip).toHaveClass("green");
    expect(kfChip).toHaveClass("stale");
  });
});
