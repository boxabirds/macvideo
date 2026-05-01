import { act, render } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";
import type { Scene } from "../types";
import { useAudioPlayback, type UseAudioPlaybackResult } from "./useAudioPlayback";

function makeScene(i: number, start: number, end: number): Scene {
  return {
    index: i,
    kind: "lyric",
    target_text: `line ${i}`,
    start_s: start,
    end_s: end,
    target_duration_s: end - start,
    num_frames: 1,
    beat: null,
    camera_intent: null,
    subject_focus: null,
    prev_link: null,
    next_link: null,
    image_prompt: null,
    prompt_is_user_authored: false,
    selected_keyframe_path: null,
    selected_clip_path: null,
    missing_assets: [],
    dirty_flags: [],
  };
}

type HarnessProps = {
  scenes: Scene[];
  onResult: (r: UseAudioPlaybackResult) => void;
};

function Harness({ scenes, onResult }: HarnessProps) {
  const result = useAudioPlayback({ scenes });
  useEffect(() => { onResult(result); });
  return <audio ref={result.audioRef} data-testid="audio" />;
}

function mountHook(scenes: Scene[]) {
  let result!: UseAudioPlaybackResult;
  const { container, unmount, rerender } = render(
    <Harness scenes={scenes} onResult={r => { result = r; }} />,
  );
  const audio = container.querySelector("audio")! as HTMLAudioElement;
  // Helper to peek at the latest hook result after React commits.
  const get = () => result;
  return { audio, get, unmount, rerender, container };
}

function setCurrentTime(audio: HTMLAudioElement, t: number) {
  Object.defineProperty(audio, "currentTime", {
    value: t, writable: true, configurable: true,
  });
}

describe("useAudioPlayback", () => {
  it("initialises playingSceneIdx to the first scene's index", () => {
    const scenes = [makeScene(1, 0, 1), makeScene(2, 1, 2)];
    const { get } = mountHook(scenes);
    expect(get().playingSceneIdx).toBe(1);
  });

  it("initialises playingSceneIdx to null for an empty scenes array", () => {
    const { get } = mountHook([]);
    expect(get().playingSceneIdx).toBe(null);
  });

  it("updates playingSceneIdx when timeupdate crosses a boundary", async () => {
    const scenes = [makeScene(1, 0, 1), makeScene(2, 1, 2), makeScene(3, 2, 3)];
    const { audio, get } = mountHook(scenes);
    setCurrentTime(audio, 1.5);
    await act(async () => { audio.dispatchEvent(new Event("timeupdate")); });
    expect(get().playingSceneIdx).toBe(2);
  });

  it("does not call setState on timeupdate within the same scene", async () => {
    const scenes = [makeScene(1, 0, 1), makeScene(2, 1, 2)];
    const { audio, get } = mountHook(scenes);
    // First, land in scene 1
    setCurrentTime(audio, 0.2);
    await act(async () => { audio.dispatchEvent(new Event("timeupdate")); });
    const before = get();
    // Tick again at 0.7s — still in scene 1. Should be the same identity.
    setCurrentTime(audio, 0.7);
    await act(async () => { audio.dispatchEvent(new Event("timeupdate")); });
    const after = get();
    expect(after.playingSceneIdx).toBe(1);
    // Functional setState with `prev === nextIdx` short-circuits; React skips
    // the re-render and the result identity is stable.
    expect(after.playingSceneIdx).toBe(before.playingSceneIdx);
  });

  it("seekToScene writes audio.currentTime to the scene's start_s", () => {
    const scenes = [makeScene(1, 0, 1), makeScene(2, 1.5, 2.5)];
    const { audio, get } = mountHook(scenes);
    let written: number | null = null;
    Object.defineProperty(audio, "currentTime", {
      get() { return 0; },
      set(v) { written = v; },
      configurable: true,
    });
    act(() => { get().seekToScene(2); });
    expect(written).toBe(1.5);
  });

  it("seekToScene does not restart the same scene while it is already playing", () => {
    const scenes = [makeScene(1, 0, 1), makeScene(2, 1.5, 2.5)];
    const { audio, get } = mountHook(scenes);
    let writeCount = 0;
    Object.defineProperty(audio, "paused", { value: false, configurable: true });
    Object.defineProperty(audio, "currentTime", {
      get() { return 0.4; },
      set() { writeCount++; },
      configurable: true,
    });
    act(() => { get().seekToScene(1); });
    expect(writeCount).toBe(0);
  });

  it("seekToScene with an unknown index is a no-op", () => {
    const scenes = [makeScene(1, 0, 1)];
    const { audio, get } = mountHook(scenes);
    let writeCount = 0;
    Object.defineProperty(audio, "currentTime", {
      get() { return 0; },
      set() { writeCount++; },
      configurable: true,
    });
    act(() => { get().seekToScene(99); });
    expect(writeCount).toBe(0);
  });

  it("seekTo writes audio.currentTime to the requested seconds", () => {
    const { audio, get } = mountHook([makeScene(1, 0, 1)]);
    let written: number | null = null;
    Object.defineProperty(audio, "currentTime", {
      get() { return 0; },
      set(v) { written = v; },
      configurable: true,
    });
    act(() => { get().seekTo(4.2); });
    expect(written).toBe(4.2);
  });

  it("loops the selected scene back to its start when loop is enabled", async () => {
    const scenes = [makeScene(1, 0, 1), makeScene(2, 1, 2)];
    const { audio, get } = mountHook(scenes);
    let internalT = 1.05;
    Object.defineProperty(audio, "paused", { value: false, configurable: true });
    Object.defineProperty(audio, "currentTime", {
      get() { return internalT; },
      set(v) { internalT = v; },
      configurable: true,
    });
    const playSpy = vi.spyOn(audio, "play").mockResolvedValue(undefined);
    await act(async () => { audio.dispatchEvent(new Event("timeupdate")); });
    expect(internalT).toBe(0);
    expect(get().playingSceneIdx).toBe(1);
    expect(playSpy).toHaveBeenCalled();
  });

  it("Option-Space toggles playback outside editable fields", async () => {
    const scenes = [makeScene(1, 0, 1)];
    const { audio } = mountHook(scenes);
    Object.defineProperty(audio, "paused", { value: true, configurable: true });
    const playSpy = vi.spyOn(audio, "play").mockResolvedValue(undefined);
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { altKey: true, code: "Space" }));
    });
    expect(playSpy).toHaveBeenCalled();
  });

  it("stop pauses playback", () => {
    const scenes = [makeScene(1, 0, 1)];
    const { audio, get } = mountHook(scenes);
    const pauseSpy = vi.spyOn(audio, "pause").mockImplementation(() => {});
    act(() => { get().stop(); });
    expect(pauseSpy).toHaveBeenCalled();
  });

  it("does not write audio.currentTime in response to a timeupdate (regression: no feedback loop)", async () => {
    // The story 13 bug: a useEffect keyed off scene-index state seeked the
    // audio backward whenever the audio crossed a boundary. The fix moves
    // ALL audio writes into seekToScene/seekTo. Verify no write happens
    // when only timeupdate fires.
    const scenes = [makeScene(1, 0, 1), makeScene(2, 1, 2)];
    const { audio, get } = mountHook(scenes);
    let writeCount = 0;
    let internalT = 1.5;
    Object.defineProperty(audio, "currentTime", {
      get() { return internalT; },
      set(v) { writeCount++; internalT = v; },
      configurable: true,
    });
    await act(async () => { audio.dispatchEvent(new Event("timeupdate")); });
    expect(get().playingSceneIdx).toBe(2); // boundary detected
    expect(writeCount).toBe(0);             // but no seek issued
  });

  it("cleans up audio listeners on unmount", () => {
    const scenes = [makeScene(1, 0, 1)];
    const { audio, unmount } = mountHook(scenes);
    const removeSpy = vi.spyOn(audio, "removeEventListener");
    unmount();
    // Four event types subscribed in the hook: timeupdate, seeked, play, pause
    const removed = removeSpy.mock.calls.map(c => c[0]);
    expect(removed).toEqual(expect.arrayContaining(["timeupdate", "seeked", "play", "pause"]));
  });
});
