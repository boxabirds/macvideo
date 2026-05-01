import type { RegenRunSummary } from "../api";
import type {
  BackendWorkflowStage,
  SongDetail,
  StageProgressView,
  StageStatus,
  WorkflowActionState,
  WorkflowRunRef,
} from "../types";

export type StageKey =
  | "transcription" | "world_brief" | "storyboard"
  | "image_prompts" | "keyframes" | "final_video";

export type StageScope =
  | "stage_transcribe" | "stage_audio_transcribe" | "stage_world_brief"
  | "stage_storyboard" | "stage_image_prompts" | "stage_keyframes"
  | "final_video";

export type StageHistoryModel = "replace" | "take";

export type StageDef = {
  key: StageKey;
  label: string;
  stageName: string;
  scope: StageScope;
  historyModel: StageHistoryModel;
};

export type SegmentStatus = "done" | "running" | "failed" | "pending" | "blocked";

export type StageDoneState = "done" | "progress" | "empty" | "error";

export type WorkflowStageState = {
  def: StageDef;
  status: SegmentStatus;
  actionState: WorkflowActionState | "legacy";
  doneState: StageDoneState;
  summary: string;
  activeRun: RegenRunSummary | undefined;
  failedRun: RegenRunSummary | undefined;
  tooltipPrereqs: string[];
  blockedReason: string | null;
  staleReasons: string[];
  progress: StageProgressView | null;
};

export const STAGES: readonly StageDef[] = [
  { key: "transcription",  label: "transcription",     stageName: "transcribe",    scope: "stage_transcribe",         historyModel: "replace" },
  { key: "world_brief",    label: "world description", stageName: "world-brief",   scope: "stage_world_brief",       historyModel: "replace" },
  { key: "storyboard",     label: "storyboard",        stageName: "storyboard",    scope: "stage_storyboard",         historyModel: "replace" },
  { key: "image_prompts",  label: "image prompts",     stageName: "image-prompts", scope: "stage_image_prompts",      historyModel: "replace" },
  { key: "keyframes",      label: "keyframes",         stageName: "keyframes",     scope: "stage_keyframes",          historyModel: "take" },
  { key: "final_video",    label: "final video",       stageName: "render-final",  scope: "final_video",              historyModel: "replace" },
] as const;

export const STAGE_PREREQS: Record<StageKey, StageKey[]> = {
  transcription: [],
  world_brief:   ["transcription"],
  storyboard:    ["world_brief"],
  image_prompts: ["storyboard"],
  keyframes:     ["image_prompts"],
  final_video:   ["keyframes"],
};

export function deriveDoneState(
  stage: StageDef, song: SongDetail, status: StageStatus, finishedCount: number,
): { doneState: StageDoneState; summary: string } {
  if (stage.key === "keyframes") {
    const done = status.keyframes_done;
    const total = status.keyframes_total;
    return {
      doneState: done === total && total > 0 ? "done" : done > 0 ? "progress" : "empty",
      summary: ` (${done}/${total})`,
    };
  }
  if (stage.key === "image_prompts") {
    const total = song.scenes.length;
    const withPrompt = song.scenes.filter(s => s.image_prompt).length;
    return {
      doneState: withPrompt === total && total > 0 ? "done" : withPrompt > 0 ? "progress" : "empty",
      summary: ` (${withPrompt}/${total})`,
    };
  }
  if (stage.key === "final_video") {
    return {
      doneState: finishedCount > 0 ? "done" : "empty",
      summary: "",
    };
  }
  return {
    doneState: stage.key === "transcription"
      ? status.transcription
      : stage.key === "world_brief"
        ? status.world_brief
        : stage.key === "storyboard"
          ? status.storyboard
          : "empty",
    summary: "",
  };
}

export function deriveSegmentStatus(args: {
  doneState: StageDoneState;
  activeRun: RegenRunSummary | undefined;
  failedRun: RegenRunSummary | undefined;
  prereqsDone: boolean;
}): SegmentStatus {
  const { doneState, activeRun, failedRun, prereqsDone } = args;
  if (activeRun) return "running";
  if (failedRun) return "failed";
  if (doneState === "error") return "failed";
  if (doneState === "done") return "done";
  if (doneState === "progress") return prereqsDone ? "pending" : "blocked";
  return prereqsDone ? "pending" : "blocked";
}

export function stageMatchesRun(stage: StageDef, run: RegenRunSummary): boolean {
  return stage.key === "transcription"
    ? (run.scope === "stage_transcribe" || run.scope === "stage_audio_transcribe")
    : run.scope === stage.scope;
}

export function deriveSongWorkflowState(args: {
  song: SongDetail;
  status: StageStatus;
  regenRuns?: RegenRunSummary[];
  finishedCount: number;
  dismissedFailedTranscribeId?: number | null;
  visibleFailedRunIds?: ReadonlySet<number>;
}): Record<StageKey, WorkflowStageState> {
  const { song, status, finishedCount, dismissedFailedTranscribeId = null, visibleFailedRunIds } = args;
  if (song.workflow?.stages) {
    return deriveBackendWorkflowState(song, dismissedFailedTranscribeId, visibleFailedRunIds);
  }
  const regenRuns = args.regenRuns ?? [];
  return STAGES.reduce((acc, stage) => {
    const { doneState, summary } = deriveDoneState(stage, song, status, finishedCount);
    const stageRuns = regenRuns.filter(run => stageMatchesRun(stage, run));
    const activeRun = stageRuns.find(run => run.status === "pending" || run.status === "running");
    const latestTerm = stageRuns.find(run => run.status === "done" || run.status === "failed" || run.status === "cancelled");
    const failedRun = latestTerm?.status === "failed"
      && !(stage.key === "transcription" && latestTerm.id === dismissedFailedTranscribeId)
      && shouldShowFailedRun(latestTerm.id, visibleFailedRunIds)
      ? latestTerm
      : undefined;
    const prereqsDone = STAGE_PREREQS[stage.key].every(pk => acc[pk].status === "done");
    const stageStatus = deriveSegmentStatus({
      doneState, activeRun, failedRun, prereqsDone,
    });
    const tooltipPrereqs = STAGE_PREREQS[stage.key]
      .filter(pk => acc[pk].status !== "done")
      .map(pk => acc[pk].def.label);
    acc[stage.key] = {
      def: stage,
      status: stageStatus,
      actionState: "legacy",
      doneState,
      summary,
      activeRun,
      failedRun,
      tooltipPrereqs,
      blockedReason: tooltipPrereqs.length ? `Complete ${tooltipPrereqs.join(", ")} first.` : null,
      staleReasons: [],
      progress: null,
    };
    return acc;
  }, {} as Record<StageKey, WorkflowStageState>);
}

function deriveBackendWorkflowState(
  song: SongDetail,
  dismissedFailedTranscribeId: number | null,
  visibleFailedRunIds?: ReadonlySet<number>,
): Record<StageKey, WorkflowStageState> {
  return STAGES.reduce((acc, stage) => {
    const backend = song.workflow?.stages[stage.key] as BackendWorkflowStage | undefined;
    if (!backend) {
      return acc;
    }
    const activeRun = backend.active_run ? runRefToSummary(backend.active_run) : undefined;
    const failedRun = backend.failed_run
      && !(stage.key === "transcription" && backend.failed_run.id === dismissedFailedTranscribeId)
      && shouldShowFailedRun(backend.failed_run.id, visibleFailedRunIds)
      ? runRefToSummary(backend.failed_run)
      : undefined;
    const hiddenRetryableWithoutOutput = backend.state === "retryable" && !failedRun && !backend.done;
    const actionState = backend.state === "retryable" && !failedRun && backend.done ? "done" : backend.state;
    const status = hiddenRetryableWithoutOutput ? "pending" : actionStateToSegmentStatus(actionState);
    const doneState: StageDoneState = backend.done
      ? "done"
      : backend.summary && !backend.summary.includes("(0/")
        ? "progress"
        : "empty";
    acc[stage.key] = {
      def: {
        ...stage,
        label: backend.label,
        stageName: backend.stage_name,
        scope: backend.scope as StageScope,
        historyModel: backend.history_model,
      },
      status,
      actionState,
      doneState,
      summary: backend.summary,
      activeRun,
      failedRun,
      tooltipPrereqs: backend.blocked_reason ? [backend.blocked_reason] : [],
      blockedReason: backend.blocked_reason,
      staleReasons: backend.stale_reasons,
      progress: backend.progress,
    };
    return acc;
  }, {} as Record<StageKey, WorkflowStageState>);
}

function shouldShowFailedRun(id: number, visibleFailedRunIds?: ReadonlySet<number>): boolean {
  return visibleFailedRunIds == null || visibleFailedRunIds.has(id);
}

function actionStateToSegmentStatus(state: WorkflowActionState | "available"): SegmentStatus {
  if (state === "running") return "running";
  if (state === "blocked") return "blocked";
  if (state === "retryable") return "failed";
  if (state === "done") return "done";
  return "pending";
}

function runRefToSummary(run: WorkflowRunRef): RegenRunSummary {
  return {
    id: run.id,
    scope: run.scope,
    song_id: 0,
    scene_id: null,
    scene_index: null,
    artefact_kind: null,
    status: run.status as RegenRunSummary["status"],
    quality_mode: null,
    cost_estimate_usd: null,
    started_at: run.started_at,
    ended_at: run.ended_at,
    error: run.error,
    progress_pct: run.progress_pct,
    phase: run.phase,
    created_at: run.created_at,
  };
}
