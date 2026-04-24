// Shared types mirroring the backend response shapes.
export type StageStatus = {
  transcription: "empty" | "done" | "error";
  world_brief: "empty" | "done" | "error";
  storyboard: "empty" | "done" | "error";
  keyframes_done: number;
  keyframes_total: number;
  clips_done: number;
  clips_total: number;
  final: "empty" | "done";
};

export type QualityMode = "draft" | "final";

export type Song = {
  slug: string;
  audio_path: string;
  duration_s: number | null;
  size_bytes: number | null;
  filter: string | null;
  abstraction: number | null;
  quality_mode: QualityMode;
  status: StageStatus;
};

export type Scene = {
  index: number;
  kind: string;
  target_text: string;
  start_s: number;
  end_s: number;
  target_duration_s: number;
  num_frames: number;
  beat: string | null;
  camera_intent: string | null;
  subject_focus: string | null;
  prev_link: string | null;
  next_link: string | null;
  image_prompt: string | null;
  prompt_is_user_authored: boolean;
  selected_keyframe_path: string | null;
  selected_clip_path: string | null;
  missing_assets: string[];
  dirty_flags: string[];
};

export type SongDetail = {
  slug: string;
  audio_path: string;
  duration_s: number | null;
  size_bytes: number | null;
  filter: string | null;
  abstraction: number | null;
  quality_mode: QualityMode;
  world_brief: string | null;
  sequence_arc: string | null;
  scenes: Scene[];
};
