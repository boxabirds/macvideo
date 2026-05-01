import type { Scene, SongDetail } from "../types";

export const WORLD_STORYBOARD_PREREQ_MESSAGE = "Please generate the world and storyboard first.";

export type SceneArtefactKind = "keyframe" | "clip";

export type WorkflowGate =
  | { ok: true }
  | { ok: false; reason: string };

export function sceneGenerationGate(
  song: SongDetail,
  scene: Scene,
  kind: SceneArtefactKind,
): WorkflowGate {
  if (!song.world_brief || !song.sequence_arc) {
    return { ok: false, reason: WORLD_STORYBOARD_PREREQ_MESSAGE };
  }
  if (kind === "keyframe" && !scene.image_prompt) {
    return { ok: false, reason: "Please generate image prompts first." };
  }
  if (kind === "clip" && !scene.selected_keyframe_path) {
    return { ok: false, reason: "Please generate a keyframe first." };
  }
  return { ok: true };
}
