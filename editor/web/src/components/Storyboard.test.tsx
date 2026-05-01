import { fireEvent, render, screen } from "@testing-library/react";
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
    world_brief: "world",
    sequence_arc: "storyboard",
    scenes,
  };
}

function stubFetchEcho() {
  const spy = vi.fn();
  globalThis.fetch = spy;
  return spy;
}

function transcriptPayload(scene: Scene) {
  const tokens = scene.target_text.split(/\s+/).filter(Boolean);
  const step = (scene.end_s - scene.start_s) / Math.max(1, tokens.length);
  return {
    scene_index: scene.index,
    target_text: scene.target_text,
    words: tokens.map((text, i) => ({
      id: i + 1,
      word_index: i,
      text,
      start_s: scene.start_s + step * i,
      end_s: i === tokens.length - 1 ? scene.end_s : scene.start_s + step * (i + 1),
      original_text: text,
      original_start_s: scene.start_s + step * i,
      original_end_s: i === tokens.length - 1 ? scene.end_s : scene.start_s + step * (i + 1),
      correction_id: null,
      warning: null,
    })),
  };
}

async function expandAll(container: HTMLElement) {
  // Rows collapse by default; tests that inspect the body must expand.
  const expandos = container.querySelectorAll<HTMLButtonElement>(".expando");
  for (const btn of expandos) {
    await userEvent.click(btn);
  }
}

afterEach(() => vi.restoreAllMocks());

describe("Storyboard", () => {
  it("renders one scene row per scene", () => {
    const song = makeSong([makeScene({ index: 1 }), makeScene({ index: 2 })]);
    render(<Storyboard song={song} cameraIntents={["static hold", "slow push in"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    expect(screen.getByText("line 1")).toBeInTheDocument();
    expect(screen.getByText("line 2")).toBeInTheDocument();
  });

  it("renders rows collapsed by default; only header is visible", () => {
    const song = makeSong([makeScene({ index: 1 })]);
    const { container } = render(
      <Storyboard song={song} cameraIntents={["static hold"]}
        playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />,
    );
    expect(container.querySelector(".scene-row.collapsed")).toBeInTheDocument();
    // Body hidden → no beat textarea in the DOM.
    expect(container.querySelector(".scene-body")).toBeNull();
  });

  it("expando toggles the body open and shows body fields", async () => {
    const song = makeSong([makeScene({ index: 1 })]);
    const { container } = render(
      <Storyboard song={song} cameraIntents={["static hold"]}
        playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />,
    );
    const expando = container.querySelector<HTMLButtonElement>(".expando")!;
    await userEvent.click(expando);
    expect(container.querySelector(".scene-row.expanded")).toBeInTheDocument();
    expect(container.querySelector(".scene-body")).toBeInTheDocument();
  });

  it("double-clicking a collapsed scene title expands without seeking playback", async () => {
    const song = makeSong([makeScene({ index: 1 })]);
    const onSeekToScene = vi.fn();
    const { container } = render(
      <Storyboard song={song} cameraIntents={["static hold"]}
        playingSceneIdx={null} onSeekToScene={onSeekToScene} onPatch={() => {}} />,
    );
    await userEvent.dblClick(container.querySelector(".scene-title")!);
    expect(container.querySelector(".scene-row.expanded")).toBeInTheDocument();
    expect(onSeekToScene).not.toHaveBeenCalled();
  });

  it("renders the time range on the scene header", () => {
    const song = makeSong([makeScene({ index: 1, start_s: 0.0, end_s: 3.3 })]);
    const { container } = render(
      <Storyboard song={song} cameraIntents={["static hold"]}
        playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />,
    );
    expect(container.querySelector(".scene-time")?.textContent).toBe(
      "[0.0s – 3.3s]",
    );
  });

  it("transcript correction: selecting words opens modal and posts correction", async () => {
    const song = makeSong([makeScene({ index: 1, target_text: "old lyric" })]);
    const scene = song.scenes[0]!;
    const onPatch = vi.fn();
    const corrected = {
      ...transcriptPayload({ ...scene, target_text: "new lyric" }),
      target_text: "new lyric",
    };
    const fetchSpy = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/transcript") && !init?.method) {
        return { ok: true, status: 200, json: async () => transcriptPayload(scene) } as Response;
      }
      if (url.endsWith("/transcript/corrections")) {
        return { ok: true, status: 200, json: async () => corrected } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    globalThis.fetch = fetchSpy;

    const { container } = render(
      <Storyboard song={song} cameraIntents={["static hold"]}
        playingSceneIdx={null} onSeekToScene={() => {}} onPatch={onPatch} />,
    );
    await expandAll(container);
    expect(screen.getByText("Transcript")).toBeInTheDocument();
    expect(screen.getByText("Visual beat")).toBeInTheDocument();
    const word = await screen.findByRole("button", { name: "old" });
    await userEvent.click(word);
    await userEvent.click(screen.getByRole("button", { name: /Edit/i }));
    const input = screen.getByDisplayValue("old");
    await userEvent.clear(input);
    await userEvent.type(input, "new lyric");
    await userEvent.click(screen.getByRole("button", { name: /Make Correction/i }));
    await new Promise(r => setTimeout(r, 20));
    const patchCall = fetchSpy.mock.calls.find(c =>
      String(c[0]).endsWith("/transcript/corrections"),
    );
    expect(patchCall).toBeTruthy();
    expect(JSON.parse((patchCall![1] as RequestInit).body as string))
      .toEqual({ start_word_index: 0, end_word_index: 0, text: "new lyric" });
    expect(onPatch).toHaveBeenCalledWith(1, expect.objectContaining({ target_text: "new lyric" }));
  });

  it("Story 27: correction controls preserve playback anchors from timed words", async () => {
    const song = makeSong([makeScene({ index: 1, target_text: "alpha beta", start_s: 10, end_s: 14 })]);
    const scene = song.scenes[0]!;
    const onSeekToTime = vi.fn();
    const corrected = {
      scene_index: 1,
      target_text: "alpha gamma delta",
      words: [
        ...transcriptPayload(scene).words.slice(0, 1),
        {
          id: 10,
          word_index: 1,
          text: "gamma",
          start_s: 12,
          end_s: 13,
          original_text: "beta",
          original_start_s: 12,
          original_end_s: 14,
          correction_id: 99,
          warning: null,
        },
        {
          id: 11,
          word_index: 2,
          text: "delta",
          start_s: 13,
          end_s: 14,
          original_text: "beta",
          original_start_s: 12,
          original_end_s: 14,
          correction_id: 99,
          warning: null,
        },
      ],
    };
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/transcript") && !init?.method) {
        return { ok: true, status: 200, json: async () => transcriptPayload(scene) } as Response;
      }
      if (url.endsWith("/transcript/corrections")) {
        return { ok: true, status: 200, json: async () => corrected } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });

    const { container } = render(
      <Storyboard song={song} cameraIntents={["static hold"]}
        playingSceneIdx={null} onSeekToScene={() => {}} onSeekToTime={onSeekToTime} onPatch={() => {}} />,
    );
    await expandAll(container);
    await userEvent.click(await screen.findByRole("button", { name: "beta" }));
    await userEvent.click(screen.getByRole("button", { name: /Edit/i }));
    const input = screen.getByDisplayValue("beta");
    await userEvent.clear(input);
    await userEvent.type(input, "gamma delta");
    await userEvent.click(screen.getByRole("button", { name: /Make Correction/i }));
    await screen.findByRole("button", { name: "gamma" });

    await userEvent.click(screen.getByRole("button", { name: "gamma" }));
    expect(onSeekToTime).toHaveBeenLastCalledWith(12);
    await userEvent.click(screen.getByRole("button", { name: "delta" }));
    expect(onSeekToTime).toHaveBeenLastCalledWith(13);
  });

  it("clicking a transcript word seeks playback to that word start", async () => {
    const song = makeSong([makeScene({ index: 1, target_text: "first second", start_s: 10, end_s: 14 })]);
    const scene = song.scenes[0]!;
    const onSeekToTime = vi.fn();
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/transcript")) {
        return { ok: true, status: 200, json: async () => transcriptPayload(scene) } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    const { container } = render(
      <Storyboard song={song} cameraIntents={["static hold"]}
        playingSceneIdx={null} onSeekToScene={() => {}} onSeekToTime={onSeekToTime} onPatch={() => {}} />,
    );
    await expandAll(container);
    await userEvent.click(await screen.findByRole("button", { name: "second" }));
    expect(onSeekToTime).toHaveBeenCalledWith(12);
  });

  it("ending a transcript drag seeks playback to the first selected word", async () => {
    const song = makeSong([makeScene({ index: 1, target_text: "one two three", start_s: 0, end_s: 9 })]);
    const scene = song.scenes[0]!;
    const onSeekToTime = vi.fn();
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/transcript")) {
        return { ok: true, status: 200, json: async () => transcriptPayload(scene) } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    const { container } = render(
      <Storyboard song={song} cameraIntents={["static hold"]}
        playingSceneIdx={null} onSeekToScene={() => {}} onSeekToTime={onSeekToTime} onPatch={() => {}} />,
    );
    await expandAll(container);
    const one = await screen.findByRole("button", { name: "one" });
    const three = await screen.findByRole("button", { name: "three" });
    fireEvent.mouseDown(one, { button: 0, buttons: 1 });
    fireEvent.mouseEnter(three, { buttons: 1 });
    fireEvent.mouseUp(three);
    expect(onSeekToTime).toHaveBeenCalledWith(0);
  });

  it("renders an empty transcript separately from a populated visual beat", async () => {
    const song = makeSong([makeScene({ index: 1, target_text: "", beat: "camera finds the empty room" })]);
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ scene_index: 1, target_text: "", words: [] }),
    } as Response);
    const { container } = render(
      <Storyboard song={song} cameraIntents={["static hold"]}
        playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />,
    );
    expect(screen.getByText("(empty phrase)")).toBeInTheDocument();
    await expandAll(container);
    expect(screen.getByText("Transcript")).toBeInTheDocument();
    expect(screen.getByText("Visual beat")).toBeInTheDocument();
    expect(await screen.findByText("No transcript words")).toBeInTheDocument();
    expect(screen.getByDisplayValue("camera finds the empty room")).toBeInTheDocument();
  });

  it("saves on blur via PATCH and calls onPatch", async () => {
    const song = makeSong([makeScene({ index: 1, beat: "old" })]);
    const onPatch = vi.fn();
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ ...song.scenes[0], beat: "new" }),
    } as Response);
    globalThis.fetch = fetchSpy;

    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={onPatch} />);
    await expandAll(container);

    const beatField = screen.getByDisplayValue("old");
    await userEvent.tripleClick(beatField);
    await userEvent.keyboard("new");
    beatField.blur();
    await new Promise(r => setTimeout(r, 0));
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/songs/tiny/scenes/1",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("shows hand-authored indicator when prompt_is_user_authored", async () => {
    const song = makeSong([
      makeScene({ index: 1, prompt_is_user_authored: true }),
    ]);
    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    await expandAll(container);
    expect(screen.getByText(/hand-authored/i)).toBeInTheDocument();
  });

  it("status chips: done (green dot) when asset present and not stale", () => {
    const song = makeSong([
      makeScene({ index: 1,
        selected_keyframe_path: "/x/keyframes/kf.png",
      }),
    ]);
    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    const kfChip = container.querySelector(".chip.keyframe");
    expect(kfChip).toHaveClass("done");
  });

  it("status chips: pending (amber dot) when asset present but stale", () => {
    const song = makeSong([
      makeScene({ index: 1,
        selected_keyframe_path: "/x/keyframes/kf.png",
        dirty_flags: ["keyframe_stale"],
      }),
    ]);
    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    const kfChip = container.querySelector(".chip.keyframe");
    expect(kfChip).toHaveClass("pending");
  });

  it("status chips: error (⚠) when asset is missing", () => {
    const song = makeSong([
      makeScene({ index: 1,
        selected_keyframe_path: null,
        missing_assets: ["keyframe"],
      }),
    ]);
    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    const kfChip = container.querySelector(".chip.keyframe");
    expect(kfChip).toHaveClass("error");
  });

  it("status chips: in-progress (spinning ↻) when a regen is active for that artefact", () => {
    const song = makeSong([
      makeScene({ index: 1, selected_keyframe_path: "/x/kf.png" }),
    ]);
    const activeRegens = { 1: new Set<"keyframe" | "clip">(["keyframe"]) };
    const { container } = render(
      <Storyboard song={song} cameraIntents={["static hold"]}
        playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}}
        activeRegens={activeRegens} />,
    );
    const kfChip = container.querySelector(".chip.keyframe");
    expect(kfChip).toHaveClass("in_progress");
    const glyph = kfChip!.querySelector(".chip-glyph");
    expect(glyph).toHaveClass("spin");
  });

  it("shows a dirty dot while the buffer diverges from saved value", async () => {
    stubFetchEcho();
    const song = makeSong([makeScene({ index: 1, beat: "old" })]);
    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    await expandAll(container);
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
    globalThis.fetch = fetchSpy;

    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    await expandAll(container);
    const beatField = screen.getByDisplayValue("old");
    await userEvent.tripleClick(beatField);
    await userEvent.keyboard("new value");
    beatField.blur();
    await new Promise(r => setTimeout(r, 10));

    expect(container.querySelector(".field-badge.error")).toBeInTheDocument();
    expect(beatField).toHaveClass("field-error");
    expect((beatField as HTMLTextAreaElement).value).toBe("new value");
  });

  it("failed transcript correction keeps the typed correction and does not overwrite visual beat", async () => {
    const song = makeSong([makeScene({ index: 1, target_text: "old phrase", beat: "visual plan" })]);
    const scene = song.scenes[0]!;
    const fetchSpy = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/transcript") && !init?.method) {
        return { ok: true, status: 200, json: async () => transcriptPayload(scene) } as Response;
      }
      return {
        ok: false, status: 500,
        json: async () => ({ detail: "boom" }),
      } as Response;
    });
    globalThis.fetch = fetchSpy;

    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    await expandAll(container);
    await userEvent.click(await screen.findByRole("button", { name: "old" }));
    await userEvent.click(screen.getByRole("button", { name: /Edit/i }));
    const phraseField = screen.getByDisplayValue("old");
    await userEvent.clear(phraseField);
    await userEvent.type(phraseField, "corrected phrase");
    await userEvent.click(screen.getByRole("button", { name: /Make Correction/i }));
    await new Promise(r => setTimeout(r, 20));

    expect((phraseField as HTMLInputElement).value).toBe("corrected phrase");
    expect(screen.getByDisplayValue("visual plan")).toBeInTheDocument();
    expect(screen.getByText(/HTTP 500/)).toBeInTheDocument();
  });

  it("undo shortcut restores transcript history without editing timestamps directly", async () => {
    const song = makeSong([makeScene({ index: 1, target_text: "new lyric" })]);
    const scene = song.scenes[0]!;
    const onPatch = vi.fn();
    const restored = transcriptPayload({ ...scene, target_text: "old lyric" });
    const fetchSpy = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/transcript") && !init?.method) {
        return { ok: true, status: 200, json: async () => transcriptPayload(scene) } as Response;
      }
      if (url.endsWith("/transcript/undo")) {
        return { ok: true, status: 200, json: async () => restored } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    globalThis.fetch = fetchSpy;

    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={1} onSeekToScene={() => {}} onPatch={onPatch} />);
    await expandAll(container);
    await screen.findByRole("button", { name: "new" });
    fireEvent.keyDown(window, { key: "z", metaKey: true });
    await new Promise(r => setTimeout(r, 20));

    expect(fetchSpy.mock.calls.some(c => String(c[0]).endsWith("/transcript/undo"))).toBe(true);
    expect(onPatch).toHaveBeenCalledWith(1, expect.objectContaining({ target_text: "old lyric" }));
    expect(await screen.findByRole("button", { name: "old" })).toBeInTheDocument();
  });

  it("does not re-fire PATCH on blur when value is unchanged", async () => {
    const song = makeSong([makeScene({ index: 1, beat: "stable" })]);
    const fetchSpy = stubFetchEcho();
    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    await expandAll(container);
    const beatField = screen.getByDisplayValue("stable");
    beatField.focus();
    beatField.blur();
    await new Promise(r => setTimeout(r, 0));
    expect(fetchSpy.mock.calls.some(c => (c[1] as RequestInit | undefined)?.method === "PATCH")).toBe(false);
  });

  it("queues edit on network failure and shows offline error", async () => {
    const song = makeSong([makeScene({ index: 1, beat: "old" })]);
    // fetch throws TypeError — what the browser does when offline.
    const fetchSpy = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    globalThis.fetch = fetchSpy;

    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    await expandAll(container);
    const beatField = screen.getByDisplayValue("old");
    await userEvent.tripleClick(beatField);
    await userEvent.keyboard("queued edit");
    beatField.blur();
    await new Promise(r => setTimeout(r, 10));

    const errBadge = container.querySelector(".field-badge.error");
    expect(errBadge).toBeInTheDocument();
    expect(errBadge?.getAttribute("title")).toMatch(/offline/i);
  });

  it("scene-row click invokes onSeekToScene with the scene's index (story 13)", async () => {
    const song = makeSong([makeScene({ index: 1 }), makeScene({ index: 2 })]);
    const onSeekToScene = vi.fn();
    const { container } = render(
      <Storyboard song={song} cameraIntents={["static hold"]}
        playingSceneIdx={null} onSeekToScene={onSeekToScene} onPatch={() => {}} />,
    );
    const headers = container.querySelectorAll<HTMLElement>(".scene-header");
    await userEvent.click(headers[1]!);
    expect(onSeekToScene).toHaveBeenCalledWith(2);
  });

  it("clicking inside the expanded editor body does not retrigger scene playback", async () => {
    const song = makeSong([makeScene({ index: 1 })]);
    const onSeekToScene = vi.fn();
    const { container } = render(
      <Storyboard song={song} cameraIntents={["static hold"]}
        playingSceneIdx={1} onSeekToScene={onSeekToScene} onPatch={() => {}} />,
    );
    await expandAll(container);
    await userEvent.click(screen.getByDisplayValue("original beat"));
    expect(onSeekToScene).not.toHaveBeenCalled();
  });

  it("scrolls the currently-selected scene into view", () => {
    const song = makeSong([makeScene({ index: 1 }), makeScene({ index: 2 })]);
    const scrollSpy = vi.fn();
    // jsdom doesn't implement scrollIntoView.
    Element.prototype.scrollIntoView = scrollSpy;

    const { rerender } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    rerender(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={2} onSeekToScene={() => {}} onPatch={() => {}} />);
    expect(scrollSpy).toHaveBeenCalled();
  });

  it("opens a confirm dialog on the ⟳ keyframe button with a cost estimate", async () => {
    stubFetchEcho();
    const song = makeSong([makeScene({ index: 1 })]);
    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    await expandAll(container);
    const btn = screen.getByTitle("regenerate keyframe");
    await userEvent.click(btn);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/\$0\.04/)).toBeInTheDocument();
    expect(screen.getByText(/~16s/)).toBeInTheDocument();
  });

  it("hides the legacy scene refresh button", async () => {
    stubFetchEcho();
    const song = makeSong([makeScene({ index: 1 })]);
    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    await expandAll(container);
    expect(screen.queryByRole("button", { name: /refresh/i })).not.toBeInTheDocument();
  });

  it("blocks scene regeneration until world and storyboard exist", async () => {
    const song = {
      ...makeSong([makeScene({ index: 1 })]),
      world_brief: null,
      sequence_arc: null,
    };
    const scene = song.scenes[0]!;
    const fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/transcript")) {
        return { ok: true, status: 200, json: async () => transcriptPayload(scene) } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    globalThis.fetch = fetchSpy;
    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    await expandAll(container);
    await userEvent.click(screen.getByTitle("regenerate keyframe"));
    expect(screen.getByText("Please generate the world and storyboard first.")).toBeInTheDocument();
    expect(fetchSpy.mock.calls.some(c => String(c[0]).includes("/takes"))).toBe(false);
  });

  it("POSTs to /takes when the regen confirm button fires", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ run_id: 1, status: "pending", estimated_seconds: 15 }),
    } as Response);
    globalThis.fetch = fetchSpy;
    const song = makeSong([makeScene({ index: 1 })]);
    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    await expandAll(container);
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
    globalThis.fetch = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PATCH") return patchSpy();
      return takesSpy();
    });
    const song = makeSong([makeScene({ index: 1 })]);
    const { container } = render(<Storyboard song={song} cameraIntents={["static hold"]}
      playingSceneIdx={null} onSeekToScene={() => {}} onPatch={() => {}} />);
    await expandAll(container);
    await userEvent.click(screen.getByTitle("show takes for this scene"));
    await new Promise(r => setTimeout(r, 10));
    const takeBtn = await screen.findByText(/\[keyframe\]/);
    await userEvent.click(takeBtn);
    await new Promise(r => setTimeout(r, 10));
    expect(patchSpy).toHaveBeenCalled();
  });
});
