import { describe, expect, it } from "vitest";
import type { RegenRunSummary } from "../api";
import type { Scene, SongDetail, StageStatus } from "../types";
import { deriveSongWorkflowState } from "./songWorkflowState";

function run(overrides: Partial<RegenRunSummary>): RegenRunSummary {
  return {
    id: 1,
    scope: "stage_world_brief",
    song_id: 1,
    scene_id: null,
    scene_index: null,
    artefact_kind: null,
    status: "failed",
    quality_mode: null,
    cost_estimate_usd: null,
    started_at: 1,
    ended_at: 2,
    error: null,
    progress_pct: null,
    phase: null,
    created_at: 2,
    ...overrides,
  };
}

function scene(partial: Partial<Scene> = {}): Scene {
  return {
    index: 1,
    kind: "lyric",
    target_text: "line",
    start_s: 0,
    end_s: 1,
    target_duration_s: 1,
    num_frames: 24,
    beat: "beat",
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
    ...partial,
  };
}

function song(partial: Partial<SongDetail> = {}): SongDetail {
  return {
    slug: "tiny",
    audio_path: "/tiny.wav",
    duration_s: 10,
    size_bytes: 100,
    filter: "charcoal",
    abstraction: 0,
    quality_mode: "draft",
    world_brief: null,
    sequence_arc: null,
    scenes: [scene()],
    ...partial,
  };
}

function status(partial: Partial<StageStatus> = {}): StageStatus {
  return {
    transcription: "done",
    world_brief: "empty",
    storyboard: "empty",
    keyframes_done: 0,
    keyframes_total: 1,
    clips_done: 0,
    clips_total: 1,
    final: "empty",
    ...partial,
  };
}

describe("deriveSongWorkflowState", () => {
  it("centralizes an instant failed world-generation run as retryable failed state", () => {
    const state = deriveSongWorkflowState({
      song: song(),
      status: status(),
      finishedCount: 0,
      regenRuns: [run({ error: null })],
    });
    expect(state.world_brief.status).toBe("failed");
    expect(state.world_brief.failedRun?.scope).toBe("stage_world_brief");
    expect(state.storyboard.status).toBe("blocked");
  });

  it("active stage runs win over older failed runs during retry", () => {
    const state = deriveSongWorkflowState({
      song: song(),
      status: status(),
      finishedCount: 0,
      regenRuns: [
        run({ id: 2, status: "running", error: null, ended_at: null, created_at: 2 }),
        run({ id: 1, status: "failed", error: "old", created_at: 1 }),
      ],
    });
    expect(state.world_brief.status).toBe("running");
    expect(state.world_brief.activeRun?.id).toBe(2);
  });

  it("uses serialized backend workflow state instead of frontend prereq rules", () => {
    const state = deriveSongWorkflowState({
      song: song({
        workflow: {
          stages: {
            transcription: {
              key: "transcription", label: "transcription", stage_name: "transcribe",
              scope: "stage_transcribe", history_model: "replace", state: "done",
              done: true, available: true, can_start: true, can_retry: false,
              blocked_reason: null, failed_reason: null, stale_reasons: [],
              invalidates: [], summary: "", active_run: null, failed_run: null, progress: null,
            },
            world_brief: {
              key: "world_brief", label: "world description", stage_name: "world-brief",
              scope: "stage_world_brief", history_model: "replace", state: "blocked",
              done: false, available: false, can_start: false, can_retry: false,
              blocked_reason: "Choose a filter and abstraction first.",
              failed_reason: null, stale_reasons: [], invalidates: [], summary: "",
              active_run: null, failed_run: null, progress: null,
            },
            storyboard: {
              key: "storyboard", label: "storyboard", stage_name: "storyboard",
              scope: "stage_storyboard", history_model: "replace", state: "blocked",
              done: false, available: false, can_start: false, can_retry: false,
              blocked_reason: "Complete world description first.",
              failed_reason: null, stale_reasons: [], invalidates: [], summary: "",
              active_run: null, failed_run: null, progress: null,
            },
            image_prompts: {
              key: "image_prompts", label: "image prompts", stage_name: "image-prompts",
              scope: "stage_image_prompts", history_model: "replace", state: "blocked",
              done: false, available: false, can_start: false, can_retry: false,
              blocked_reason: "Please generate the world and storyboard first.",
              failed_reason: null, stale_reasons: [], invalidates: [], summary: "",
              active_run: null, failed_run: null, progress: null,
            },
            keyframes: {
              key: "keyframes", label: "keyframes", stage_name: "keyframes",
              scope: "stage_keyframes", history_model: "take", state: "blocked",
              done: false, available: false, can_start: false, can_retry: false,
              blocked_reason: "Please generate the world and storyboard first.",
              failed_reason: null, stale_reasons: [], invalidates: [], summary: " (0/1)",
              active_run: null, failed_run: null, progress: null,
            },
            final_video: {
              key: "final_video", label: "final video", stage_name: "render-final",
              scope: "final_video", history_model: "replace", state: "blocked",
              done: false, available: false, can_start: false, can_retry: false,
              blocked_reason: "Please generate the world and storyboard first.",
              failed_reason: null, stale_reasons: [], invalidates: [], summary: "",
              active_run: null, failed_run: null, progress: null,
            },
          },
        },
      }),
      status: status({ world_brief: "done" }),
      finishedCount: 0,
    });

    expect(state.world_brief.status).toBe("blocked");
    expect(state.world_brief.blockedReason).toBe("Choose a filter and abstraction first.");
    expect(state.keyframes.blockedReason).toBe("Please generate the world and storyboard first.");
  });
});
