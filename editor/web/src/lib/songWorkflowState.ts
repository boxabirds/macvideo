import type { RegenRunSummary } from "../api";
import type { SongDetail, StageStatus } from "../types";

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
  doneState: StageDoneState;
  summary: string;
  activeRun: RegenRunSummary | undefined;
  failedRun: RegenRunSummary | undefined;
  tooltipPrereqs: string[];
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
}): Record<StageKey, WorkflowStageState> {
  const { song, status, finishedCount, dismissedFailedTranscribeId = null } = args;
  const regenRuns = args.regenRuns ?? [];
  return STAGES.reduce((acc, stage) => {
    const { doneState, summary } = deriveDoneState(stage, song, status, finishedCount);
    const stageRuns = regenRuns.filter(run => stageMatchesRun(stage, run));
    const activeRun = stageRuns.find(run => run.status === "pending" || run.status === "running");
    const latestTerm = stageRuns.find(run => run.status === "done" || run.status === "failed" || run.status === "cancelled");
    const failedRun = latestTerm?.status === "failed"
      && !(stage.key === "transcription" && latestTerm.id === dismissedFailedTranscribeId)
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
      doneState,
      summary,
      activeRun,
      failedRun,
      tooltipPrereqs,
    };
    return acc;
  }, {} as Record<StageKey, WorkflowStageState>);
}
