import { describe, expect, it } from "vitest";
import type { Scene, SongDetail } from "../types";
import {
  WORLD_STORYBOARD_PREREQ_MESSAGE,
  sceneGenerationGate,
} from "./editorWorkflowState";

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
    image_prompt: "prompt",
    prompt_is_user_authored: false,
    selected_keyframe_path: "/kf.png",
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
    world_brief: "world",
    sequence_arc: "story",
    scenes: [scene()],
    ...partial,
  };
}

describe("sceneGenerationGate", () => {
  it("blocks scene generation until world and storyboard exist", () => {
    expect(sceneGenerationGate(song({ world_brief: null }), scene(), "keyframe"))
      .toEqual({ ok: false, reason: WORLD_STORYBOARD_PREREQ_MESSAGE });
    expect(sceneGenerationGate(song({ sequence_arc: null }), scene(), "clip"))
      .toEqual({ ok: false, reason: WORLD_STORYBOARD_PREREQ_MESSAGE });
  });

  it("blocks keyframes without image prompts and clips without keyframes", () => {
    expect(sceneGenerationGate(song(), scene({ image_prompt: null }), "keyframe"))
      .toEqual({ ok: false, reason: "Please generate image prompts first." });
    expect(sceneGenerationGate(song(), scene({ selected_keyframe_path: null }), "clip"))
      .toEqual({ ok: false, reason: "Please generate a keyframe first." });
  });

  it("allows ready keyframe and clip generation", () => {
    expect(sceneGenerationGate(song(), scene(), "keyframe")).toEqual({ ok: true });
    expect(sceneGenerationGate(song(), scene(), "clip")).toEqual({ ok: true });
  });
});
