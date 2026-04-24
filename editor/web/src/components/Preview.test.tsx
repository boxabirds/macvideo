import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Preview from "./Preview";
import type { Scene, SongDetail } from "../types";

function makeScene(i: number, extras: Partial<Scene> = {}): Scene {
  return {
    index: i,
    kind: "lyric",
    target_text: `line ${i}`,
    start_s: i,
    end_s: i + 1,
    target_duration_s: 1,
    num_frames: 33,
    beat: `beat ${i}`,
    camera_intent: "static hold",
    subject_focus: "narrator",
    prev_link: null,
    next_link: null,
    image_prompt: "prompt",
    prompt_is_user_authored: false,
    selected_keyframe_path: `/x/pocs/29-full-song/outputs/tiny/keyframes/kf_${i}.png`,
    selected_clip_path: null,
    missing_assets: [],
    dirty_flags: [],
    ...extras,
  };
}

function makeSong(scenes: Scene[]): SongDetail {
  return {
    slug: "tiny",
    audio_path: "/x/music/tiny.wav",
    duration_s: 5, size_bytes: 100, filter: null, abstraction: null,
    quality_mode: "draft", world_brief: null, sequence_arc: null, scenes,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("Preview", () => {
  it("renders a keyframe still when no clip exists", () => {
    const { container } = render(<Preview song={makeSong([makeScene(1), makeScene(2)])} currentIdx={null} />);
    const imgs = container.querySelectorAll("img");
    expect(imgs.length).toBeGreaterThan(0);
  });

  it("renders a clip video when a clip is selected", () => {
    const scenes = [makeScene(1, { selected_clip_path: "/x/pocs/29-full-song/outputs/tiny/clips/clip_001.mp4" })];
    const { container } = render(<Preview song={makeSong(scenes)} currentIdx={1} />);
    expect(container.querySelector("video")).toBeTruthy();
  });

  it("renders a thumbnail per scene in the timeline", () => {
    const scenes = [makeScene(1), makeScene(2), makeScene(3)];
    const { container } = render(<Preview song={makeSong(scenes)} currentIdx={null} />);
    const thumbs = container.querySelectorAll(".thumb");
    expect(thumbs.length).toBe(3);
  });

  it("renders a neutral placeholder when asset is missing", () => {
    const s = makeScene(1, { missing_assets: ["keyframe"], selected_keyframe_path: null });
    render(<Preview song={makeSong([s])} currentIdx={1} />);
    expect(screen.getByText(/no asset|no scene/i)).toBeInTheDocument();
  });

  it("advances the viewer via audio timeupdate events (audio is the playhead)", async () => {
    const scenes = [makeScene(1), makeScene(2), makeScene(3)];
    const { container } = render(<Preview song={makeSong(scenes)} currentIdx={null} />);
    const audio = container.querySelector("audio")!;
    // jsdom fires events but doesn't advance currentTime on its own.
    Object.defineProperty(audio, "currentTime", { value: 2.5, writable: true });
    await act(async () => {
      audio.dispatchEvent(new Event("timeupdate"));
    });
    // Caption updates to the scene at t=2.5 (scene #3 starts at index 3 i.e. 3s;
    // at t=2.5 we're in scene #2 range which the findSceneAt helper returns).
    const caption = container.querySelector(".caption");
    expect(caption?.textContent).toMatch(/#2|#3/);
  });

  it("seeks audio when a timeline thumbnail is clicked", () => {
    const scenes = [makeScene(1), makeScene(2)];
    const { container } = render(<Preview song={makeSong(scenes)} currentIdx={null} />);
    const audio = container.querySelector("audio")!;
    // Spy on currentTime setter
    let setTo: number | null = null;
    Object.defineProperty(audio, "currentTime", {
      get() { return 0; },
      set(v) { setTo = v; },
      configurable: true,
    });
    const thumbs = container.querySelectorAll(".thumb");
    (thumbs[1] as HTMLElement).click();
    // Scene 2 starts at start_s=2
    expect(setTo).toBe(2);
  });

  it("exposes a fullscreen toggle and calls requestFullscreen on click", async () => {
    const requestSpy = vi.fn().mockResolvedValue(undefined);
    // jsdom doesn't implement the Fullscreen API; stub the method we call.
    Element.prototype.requestFullscreen = requestSpy;
    Object.defineProperty(document, "fullscreenElement", { value: null, configurable: true });

    render(<Preview song={makeSong([makeScene(1)])} currentIdx={1} />);
    const button = screen.getByRole("button", { name: /full-screen/i });
    button.click();
    expect(requestSpy).toHaveBeenCalled();
  });
});
