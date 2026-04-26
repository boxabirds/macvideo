import { act, render, screen } from "@testing-library/react";
import { useRef } from "react";
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

// Test harness: Preview now requires a parent-supplied audioRef. Real
// SongEditor gets it from useAudioPlayback; tests just create a local ref.
function PreviewHarness({
  song, playingSceneIdx, onSeekToScene = () => {},
}: {
  song: SongDetail;
  playingSceneIdx: number | null;
  onSeekToScene?: (idx: number) => void;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  return (
    <Preview
      song={song}
      audioRef={audioRef}
      playingSceneIdx={playingSceneIdx}
      onSeekToScene={onSeekToScene}
    />
  );
}

afterEach(() => vi.restoreAllMocks());

describe("Preview", () => {
  it("renders a keyframe still when no clip exists", () => {
    const { container } = render(
      <PreviewHarness song={makeSong([makeScene(1), makeScene(2)])} playingSceneIdx={null} />,
    );
    const imgs = container.querySelectorAll("img");
    expect(imgs.length).toBeGreaterThan(0);
  });

  it("renders a clip video when a clip is selected", () => {
    const scenes = [makeScene(1, { selected_clip_path: "/x/pocs/29-full-song/outputs/tiny/clips/clip_001.mp4" })];
    const { container } = render(
      <PreviewHarness song={makeSong(scenes)} playingSceneIdx={1} />,
    );
    expect(container.querySelector("video")).toBeTruthy();
  });

  it("renders a thumbnail per scene in the timeline", () => {
    const scenes = [makeScene(1), makeScene(2), makeScene(3)];
    const { container } = render(
      <PreviewHarness song={makeSong(scenes)} playingSceneIdx={null} />,
    );
    const thumbs = container.querySelectorAll(".thumb");
    expect(thumbs.length).toBe(3);
  });

  it("renders a neutral placeholder when asset is missing", () => {
    const s = makeScene(1, { missing_assets: ["keyframe"], selected_keyframe_path: null });
    render(<PreviewHarness song={makeSong([s])} playingSceneIdx={1} />);
    expect(screen.getByText(/no asset|no scene/i)).toBeInTheDocument();
  });

  it("renders the scene named by playingSceneIdx in the viewer caption (story 13)", () => {
    const scenes = [makeScene(1), makeScene(2), makeScene(3)];
    const { container } = render(
      <PreviewHarness song={makeSong(scenes)} playingSceneIdx={3} />,
    );
    const caption = container.querySelector(".caption");
    expect(caption?.textContent).toMatch(/#3/);
  });

  it("changing playingSceneIdx updates the highlighted thumbnail without writing to audio (story 13)", async () => {
    const scenes = [makeScene(1), makeScene(2), makeScene(3)];
    let writeCount = 0;
    // Spy on currentTime setter on every <audio> rendered into the document.
    Object.defineProperty(HTMLAudioElement.prototype, "currentTime", {
      get() { return 0; },
      set() { writeCount++; },
      configurable: true,
    });
    const { container, rerender } = render(
      <PreviewHarness song={makeSong(scenes)} playingSceneIdx={1} />,
    );
    expect(container.querySelector(".thumb.current")?.textContent).toContain("#1");
    await act(async () => {
      rerender(<PreviewHarness song={makeSong(scenes)} playingSceneIdx={2} />);
    });
    expect(container.querySelector(".thumb.current")?.textContent).toContain("#2");
    // The bug: a useEffect keyed off currentIdx wrote audio.currentTime when
    // the prop changed. Fixed: no effect writes audio in response to a
    // playingSceneIdx change.
    expect(writeCount).toBe(0);
  });

  it("clicking a timeline thumbnail invokes onSeekToScene (not a direct audio write) (story 13)", () => {
    const scenes = [makeScene(1), makeScene(2)];
    const onSeekToScene = vi.fn();
    const { container } = render(
      <PreviewHarness song={makeSong(scenes)} playingSceneIdx={null} onSeekToScene={onSeekToScene} />,
    );
    const thumbs = container.querySelectorAll(".thumb");
    (thumbs[1] as HTMLElement).click();
    expect(onSeekToScene).toHaveBeenCalledWith(2);
  });

  it("exposes a fullscreen toggle and calls requestFullscreen on click", async () => {
    const requestSpy = vi.fn().mockResolvedValue(undefined);
    // jsdom doesn't implement the Fullscreen API; stub the method we call.
    Element.prototype.requestFullscreen = requestSpy;
    Object.defineProperty(document, "fullscreenElement", { value: null, configurable: true });

    render(<PreviewHarness song={makeSong([makeScene(1)])} playingSceneIdx={1} />);
    const button = screen.getByRole("button", { name: /full-screen/i });
    button.click();
    expect(requestSpy).toHaveBeenCalled();
  });
});
