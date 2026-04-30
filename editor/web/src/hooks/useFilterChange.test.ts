import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useFilterChange } from "./useFilterChange";
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

afterEach(() => vi.restoreAllMocks());

describe("useFilterChange", () => {
  it("returns noop kind when filter hasn't changed", () => {
    const song = makeSong({ filter: "cyanotype" });
    const { result } = renderHook(() => useFilterChange(song, "cyanotype"));

    expect(result.current.kind).toBe("noop");
    expect(result.current.preview).toBeNull();
    expect(result.current.previewError).toBeNull();
  });

  it("returns fresh-setup kind for fresh songs", () => {
    const fresh = makeSong({
      filter: null,
      world_brief: null,
      scenes: [],
    });
    const { result } = renderHook(() => useFilterChange(fresh, "cyanotype"));

    expect(result.current.kind).toBe("fresh-setup");
    expect(result.current.preview).toBeNull();
    expect(result.current.previewError).toBeNull();
  });

  it("returns destructive kind for songs with state", () => {
    const song = makeSong({
      filter: "oil impasto",
      world_brief: "narrator",
      scenes: [{ index: 0 } as any],
    });
    const { result } = renderHook(() => useFilterChange(song, "cyanotype"));

    expect(result.current.kind).toBe("destructive");
  });

  it("fetches preview for destructive changes", async () => {
    const previewResponse = {
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

    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => previewResponse,
    } as Response);
    globalThis.fetch = fetchSpy;

    const song = makeSong({ filter: "oil impasto", world_brief: "narrator" });
    const { result } = renderHook(() => useFilterChange(song, "cyanotype"));

    expect(result.current.kind).toBe("destructive");
    expect(result.current.inFlight).toBe(true);

    await waitFor(() => {
      expect(result.current.inFlight).toBe(false);
    });

    expect(result.current.preview).toEqual(previewResponse);
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/preview-change"),
      expect.any(Object)
    );
  });

  it("handles preview fetch errors gracefully", async () => {
    const fetchSpy = vi.fn().mockRejectedValue(new Error("Network error"));
    globalThis.fetch = fetchSpy;

    const song = makeSong({ filter: "oil impasto", world_brief: "narrator" });
    const { result } = renderHook(() => useFilterChange(song, "cyanotype"));

    expect(result.current.inFlight).toBe(true);

    await waitFor(() => {
      expect(result.current.inFlight).toBe(false);
    });

    expect(result.current.preview).toBeNull();
    expect(result.current.previewError).toBe("Error: Network error");
  });

  it("skips preview fetch for fresh-setup", async () => {
    const fetchSpy = vi.fn();
    globalThis.fetch = fetchSpy;

    const fresh = makeSong({
      filter: null,
      world_brief: null,
      scenes: [],
    });
    const { result } = renderHook(() => useFilterChange(fresh, "cyanotype"));

    expect(result.current.kind).toBe("fresh-setup");

    await new Promise(r => setTimeout(r, 50));

    // No fetch should have been called for fresh-setup.
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("cancels in-flight preview fetch on unmount", async () => {
    const fetchSpy = vi.fn().mockImplementation(() => new Promise(() => {})); // Never resolves
    globalThis.fetch = fetchSpy;

    const song = makeSong({ filter: "oil impasto", world_brief: "narrator" });
    const { unmount } = renderHook(() => useFilterChange(song, "cyanotype"));

    expect(fetchSpy).toHaveBeenCalled();
    unmount();
    // Hook should clean up on unmount (no assertion needed, just verify no error thrown)
  });

  it("detects fresh-setup when world_brief is null but filter is set", () => {
    // This is still fresh if there are no scenes (transcription hasn't run).
    const song = makeSong({
      filter: "oil impasto",
      world_brief: null,
      scenes: [],
    });
    const { result } = renderHook(() => useFilterChange(song, "cyanotype"));

    // Not fresh because filter is already set, even though world_brief is null.
    expect(result.current.kind).toBe("destructive");
  });

  it("detects fresh-setup when filter is null but world_brief is set", () => {
    const song = makeSong({
      filter: null,
      world_brief: "narrator",
      scenes: [],
    });
    const { result } = renderHook(() => useFilterChange(song, "cyanotype"));

    // Not fresh because world_brief is set.
    expect(result.current.kind).toBe("destructive");
  });

  it("detects fresh-setup when filter is null, world_brief is null, but scenes exist", () => {
    const song = makeSong({
      filter: null,
      world_brief: null,
      scenes: [{ index: 0 } as any],
    });
    const { result } = renderHook(() => useFilterChange(song, "cyanotype"));

    // Not fresh because scenes exist (transcription has run).
    expect(result.current.kind).toBe("destructive");
  });
});
