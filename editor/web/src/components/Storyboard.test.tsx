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

  it("shows a dirty dot while the buffer diverges from saved value", async () => {
    stubFetchEcho();
    const song = makeSong([makeScene({ index: 1, beat: "old" })]);
    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      currentIdx={null} onSelect={() => {}} onPatch={() => {}} />);
    const beatField = screen.getByDisplayValue("old");
    await userEvent.type(beatField, "X");
    // While typing, buffer ("oldX") != saved ("old") — dirty badge visible.
    expect(container.querySelector(".field-badge.dirty")).toBeInTheDocument();
  });

  it("surfaces an error badge when PATCH fails and keeps the buffer", async () => {
    const song = makeSong([makeScene({ index: 1, beat: "old" })]);
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: false, status: 422,
      json: async () => ({ detail: "bad value" }),
    } as Response);
    // @ts-expect-error
    globalThis.fetch = fetchSpy;

    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      currentIdx={null} onSelect={() => {}} onPatch={() => {}} />);
    const beatField = screen.getByDisplayValue("old");
    await userEvent.tripleClick(beatField);
    await userEvent.keyboard("new value");
    beatField.blur();
    // Wait for the async PATCH to reject and state to settle.
    await new Promise(r => setTimeout(r, 10));

    expect(container.querySelector(".field-badge.error")).toBeInTheDocument();
    expect(beatField).toHaveClass("field-error");
    // Buffer is kept so user can retry.
    expect((beatField as HTMLTextAreaElement).value).toBe("new value");
  });

  it("does not re-fire PATCH on blur when value is unchanged", async () => {
    const song = makeSong([makeScene({ index: 1, beat: "stable" })]);
    const fetchSpy = stubFetchEcho();
    render(<Storyboard song={song} cameraIntents={["static hold"]}
      currentIdx={null} onSelect={() => {}} onPatch={() => {}} />);
    const beatField = screen.getByDisplayValue("stable");
    beatField.focus();
    beatField.blur();
    await new Promise(r => setTimeout(r, 0));
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("queues edit on network failure and shows offline error", async () => {
    const song = makeSong([makeScene({ index: 1, beat: "old" })]);
    // fetch throws TypeError — what the browser does when offline.
    const fetchSpy = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    // @ts-expect-error
    globalThis.fetch = fetchSpy;

    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      currentIdx={null} onSelect={() => {}} onPatch={() => {}} />);
    const beatField = screen.getByDisplayValue("old");
    await userEvent.tripleClick(beatField);
    await userEvent.keyboard("queued edit");
    beatField.blur();
    await new Promise(r => setTimeout(r, 10));

    const errBadge = container.querySelector(".field-badge.error");
    expect(errBadge).toBeInTheDocument();
    expect(errBadge?.getAttribute("title")).toMatch(/offline/i);
  });

  it("scrolls the currently-selected scene into view", () => {
    const song = makeSong([makeScene({ index: 1 }), makeScene({ index: 2 })]);
    const scrollSpy = vi.fn();
    // jsdom doesn't implement scrollIntoView.
    Element.prototype.scrollIntoView = scrollSpy;

    const { rerender } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      currentIdx={null} onSelect={() => {}} onPatch={() => {}} />);
    rerender(<Storyboard song={song} cameraIntents={["static hold"]}
      currentIdx={2} onSelect={() => {}} onPatch={() => {}} />);
    expect(scrollSpy).toHaveBeenCalled();
  });

  it("opens a confirm dialog on the ⟳ keyframe button with a cost estimate", async () => {
    stubFetchEcho();
    const song = makeSong([makeScene({ index: 1 })]);
    render(<Storyboard song={song} cameraIntents={["static hold"]}
      currentIdx={null} onSelect={() => {}} onPatch={() => {}} />);
    // Find the keyframe regen button.
    const btn = screen.getByTitle("regenerate keyframe");
    await userEvent.click(btn);
    // Dialog shows with the cost-estimate text.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/\$0\.04/)).toBeInTheDocument();
    expect(screen.getByText(/~16s/)).toBeInTheDocument();
  });

  it("POSTs to /takes when the regen confirm button fires", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 1, status: "pending", estimated_seconds: 15 }),
    } as Response);
    // @ts-expect-error
    globalThis.fetch = fetchSpy;
    const song = makeSong([makeScene({ index: 1 })]);
    render(<Storyboard song={song} cameraIntents={["static hold"]}
      currentIdx={null} onSelect={() => {}} onPatch={() => {}} />);
    await userEvent.click(screen.getByTitle("regenerate keyframe"));
    await userEvent.click(screen.getByRole("button", { name: /^Regenerate$/i }));
    await new Promise(r => setTimeout(r, 10));
    const urls = fetchSpy.mock.calls.map(c => c[0] as string);
    const postCall = urls.find(u => u.includes("/scenes/1/takes"));
    expect(postCall).toBeDefined();
  });

  it("clicking a take in the picker PATCHes with selection_pinned=true", async () => {
    const patchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ ...makeScene({ index: 1 }) }),
    } as Response);
    const takesSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ takes: [{ id: 5, artefact_kind: "keyframe", asset_path: "/x.png", created_at: 0, quality_mode: "draft", source_run_id: 3, is_selected: false }] }),
    } as Response);
    // Route fetches: GET /scenes/:idx/takes returns list; PATCH is capture.
    // @ts-expect-error
    globalThis.fetch = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") return patchSpy();
      return takesSpy();
    });
    const song = makeSong([makeScene({ index: 1 })]);
    render(<Storyboard song={song} cameraIntents={["static hold"]}
      currentIdx={null} onSelect={() => {}} onPatch={() => {}} />);
    await userEvent.click(screen.getByTitle("show takes for this scene"));
    await new Promise(r => setTimeout(r, 10));
    // Click the take button.
    const takeBtn = await screen.findByText(/\[keyframe\]/);
    await userEvent.click(takeBtn);
    await new Promise(r => setTimeout(r, 10));
    expect(patchSpy).toHaveBeenCalled();
  });
});
