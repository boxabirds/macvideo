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
  transcript_words?: TranscriptWord[];
};

export type TranscriptWord = {
  id: number;
  word_index: number;
  text: string;
  start_s: number;
  end_s: number;
  original_text: string;
  original_start_s: number;
  original_end_s: number;
  correction_id: number | null;
  warning: string | null;
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
  workflow?: SongWorkflowView;
};

export type WorkflowActionState =
  | "done"
  | "available"
  | "blocked"
  | "running"
  | "retryable"
  | "stale";

export type WorkflowRunRef = {
  id: number;
  scope: string;
  status: string;
  error: string | null;
  progress_pct: number | null;
  phase: string | null;
  started_at: number | null;
  ended_at: number | null;
  created_at: number;
};

export type StageProgressView = {
  operation: string;
  detail: string | null;
  progress_pct: number | null;
  processed_seconds: number | null;
  total_seconds: number | null;
};

export type BackendWorkflowStage = {
  key: string;
  label: string;
  stage_name: string;
  scope: string;
  history_model: "replace" | "take";
  state: WorkflowActionState;
  done: boolean;
  available: boolean;
  can_start: boolean;
  can_retry: boolean;
  blocked_reason: string | null;
  failed_reason: string | null;
  stale_reasons: string[];
  invalidates: string[];
  summary: string;
  active_run: WorkflowRunRef | null;
  failed_run: WorkflowRunRef | null;
  progress: StageProgressView | null;
};

export type SongWorkflowView = {
  stages: Record<string, BackendWorkflowStage>;
};
