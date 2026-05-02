import { describe, expect, it } from "vitest";
import type { RegenRunSummary } from "../api";
import {
  buildActiveRegens,
  shouldRefreshSongForRegenTransition,
} from "./useRegenRuns";

function run(overrides: Partial<RegenRunSummary> = {}): RegenRunSummary {
  return {
    id: 1,
    scope: "scene_keyframe",
    song_id: 1,
    scene_id: 1,
    scene_index: 0,
    artefact_kind: "keyframe",
    status: "running",
    quality_mode: null,
    cost_estimate_usd: null,
    started_at: 10,
    ended_at: null,
    error: null,
    progress_pct: null,
    phase: null,
    created_at: 10,
    ...overrides,
  };
}

describe("regen run resilience helpers", () => {
  it("does not refresh the song for progress-only updates", () => {
    expect(shouldRefreshSongForRegenTransition(
      [run({ progress_pct: 10, phase: "rendering" })],
      [run({ progress_pct: 50, phase: "rendering" })],
    )).toBe(false);
  });

  it("refreshes the song when a known run reaches a terminal state", () => {
    expect(shouldRefreshSongForRegenTransition(
      [run({ status: "running", ended_at: null })],
      [run({ status: "done", ended_at: 20 })],
    )).toBe(true);
  });

  it("refreshes the song when a new terminal run appears after initial observation", () => {
    expect(shouldRefreshSongForRegenTransition(
      [run({ id: 1, status: "running" })],
      [run({ id: 1, status: "running" }), run({ id: 2, status: "failed", error: "boom" })],
    )).toBe(true);
  });

  it("builds active scene artefact indicators only for running scene runs", () => {
    const active = buildActiveRegens([
      run({ scene_index: 1, artefact_kind: "keyframe", status: "running" }),
      run({ id: 2, scene_index: 1, artefact_kind: "clip", status: "pending" }),
      run({ id: 3, scene_index: 2, artefact_kind: "clip", status: "done" }),
      run({ id: 4, scene_index: null, artefact_kind: "clip", status: "running" }),
    ]);

    expect(active[1]?.has("keyframe")).toBe(true);
    expect(active[1]?.has("clip")).toBe(true);
    expect(active[2]).toBeUndefined();
  });
});
