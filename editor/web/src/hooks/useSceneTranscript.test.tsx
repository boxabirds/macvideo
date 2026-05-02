import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";
import { sceneTranscriptKey, useSceneTranscript } from "./useSceneTranscript";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 2000 }}>
      {children}
    </SWRConfig>
  );
}

afterEach(() => vi.restoreAllMocks());

describe("useSceneTranscript", () => {
  it("returns no key while disabled", () => {
    expect(sceneTranscriptKey("tiny", 1, "hello", false)).toBeNull();
    expect(sceneTranscriptKey("tiny", 1, "hello", true)).toEqual([
      "scene-transcript",
      "tiny",
      1,
      "hello",
    ]);
  });

  it("deduplicates simultaneous loads for the same scene detail", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ scene_index: 1, target_text: "hello", words: [] }),
    } as Response);
    globalThis.fetch = fetchSpy;

    const { result } = renderHook(() => ({
      first: useSceneTranscript("tiny", 1, "hello", true),
      second: useSceneTranscript("tiny", 1, "hello", true),
    }), { wrapper });

    await waitFor(() => {
      expect(result.current.first.words).toEqual([]);
      expect(result.current.second.words).toEqual([]);
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("reuses the cached response when a scene is closed and reopened", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        scene_index: 1,
        target_text: "hello",
        words: [{ id: 1, word_index: 0, text: "hello" }],
      }),
    } as Response);
    globalThis.fetch = fetchSpy;

    const { result, rerender } = renderHook(
      ({ enabled }) => useSceneTranscript("tiny", 1, "hello", enabled),
      { initialProps: { enabled: true }, wrapper },
    );

    await waitFor(() => {
      expect(result.current.words?.[0]?.text).toBe("hello");
    });
    rerender({ enabled: false });
    rerender({ enabled: true });

    await waitFor(() => {
      expect(result.current.words?.[0]?.text).toBe("hello");
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
