// Thin fetch wrapper + SWR fetcher + mutation helpers.
import type { Scene, Song, SongDetail, QualityMode, TranscriptWord } from "./types";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export function formatApiError(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = error.detail as { detail?: unknown } | null;
    const payload = detail && typeof detail === "object" && "detail" in detail
      ? detail.detail
      : error.detail;
    if (typeof payload === "string") return payload;
    if (payload && typeof payload === "object") {
      const body = payload as { reason?: unknown; message?: unknown; detail?: unknown; code?: unknown };
      const message = body.reason ?? body.message ?? body.detail;
      if (typeof message === "string") return message;
      if (typeof body.code === "string") return body.code;
    }
    return `Request failed with status ${error.status}`;
  }
  return String(error);
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: unknown = null;
    try { detail = await res.json(); } catch { /* no body */ }
    throw new ApiError(res.status, detail, `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export const fetcher = async <T>(url: string): Promise<T> => handle<T>(await fetch(url));

export async function listSongs(): Promise<{ songs: Song[] }> {
  return handle(await fetch("/api/songs"));
}

export async function getSong(slug: string): Promise<SongDetail> {
  return handle(await fetch(`/api/songs/${encodeURIComponent(slug)}`));
}

export async function patchSong(
  slug: string,
  body: { filter?: string; abstraction?: number; quality_mode?: QualityMode; world_brief?: string },
): Promise<SongDetail> {
  return handle(await fetch(`/api/songs/${encodeURIComponent(slug)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }));
}

export async function getScene(slug: string, idx: number): Promise<Scene> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/scenes/${idx}`,
  ));
}

export async function patchScene(
  slug: string, idx: number,
  body: Partial<{
    beat: string;
    camera_intent: string;
    subject_focus: string;
    image_prompt: string;
    target_text: string;
    prompt_is_user_authored: boolean;
    selected_keyframe_take_id: number;
    selected_clip_take_id: number;
    selection_pinned: boolean;
  }>,
): Promise<Scene> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/scenes/${idx}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  ));
}

export async function listCameraIntents(): Promise<{ values: string[] }> {
  return handle(await fetch("/api/camera-intents"));
}

export async function triggerImport(): Promise<unknown> {
  return handle(await fetch("/api/import", { method: "POST" }));
}

export type RegenTriggerResponse = {
  run_id: number;
  status: string;
  estimated_seconds: number;
};

export async function regenerateScene(
  slug: string, idx: number,
  artefactKind: "keyframe" | "clip",
): Promise<RegenTriggerResponse> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/scenes/${idx}/takes`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ artefact_kind: artefactKind }),
    },
  ));
}

export type ChainPreview = {
  kind: "fresh-setup" | "destructive" | "noop";
  from: { filter: string | null; abstraction: number | null };
  to: { filter: string | null; abstraction: number | null };
  scope: {
    will_regen_world_brief: boolean;
    will_regen_storyboard: boolean;
    scenes_with_new_prompts: number;
    keyframes_to_generate: number;
    clips_marked_stale: number;
    clips_deleted: number;
  };
  estimate: {
    gemini_calls: number;
    estimated_usd: number;
    estimated_seconds: number;
    confidence: "high" | "medium" | "low";
  };
  would_conflict_with: { run_id: number; reason: string } | null;
};

export async function previewChange(
  slug: string,
  body: { filter?: string; abstraction?: number },
): Promise<ChainPreview> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/preview-change`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  ));
}

export type SceneTake = {
  id: number;
  artefact_kind: "keyframe" | "clip";
  asset_path: string;
  source_run_id: number | null;
  created_at: number;
  quality_mode: string | null;
  is_selected: boolean;
};

export async function listTakes(slug: string, idx: number): Promise<{ takes: SceneTake[] }> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/scenes/${idx}/takes`,
  ));
}

export type RegenRunSummary = {
  id: number;
  scope: string;
  song_id: number;
  scene_id: number | null;
  scene_index: number | null;
  artefact_kind: "keyframe" | "clip" | null;
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  quality_mode: string | null;
  cost_estimate_usd: number | null;
  started_at: number | null;
  ended_at: number | null;
  error: string | null;
  progress_pct: number | null;
  phase: string | null;
  created_at: number;
};

export type TranscriptResponse = {
  scene_index: number;
  target_text: string;
  words: TranscriptWord[];
};

export async function getSceneTranscript(slug: string, idx: number): Promise<TranscriptResponse> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/scenes/${idx}/transcript`,
  ));
}

export async function applyTranscriptCorrection(
  slug: string,
  idx: number,
  body: { start_word_index: number; end_word_index: number; text: string },
): Promise<TranscriptResponse> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/scenes/${idx}/transcript/corrections`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  ));
}

export async function revertTranscriptCorrection(
  slug: string,
  idx: number,
  correctionId: number,
): Promise<TranscriptResponse> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/scenes/${idx}/transcript/corrections/${correctionId}/revert`,
    { method: "POST" },
  ));
}

export async function undoTranscriptCorrection(slug: string): Promise<TranscriptResponse> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/transcript/undo`,
    { method: "POST" },
  ));
}

export async function redoTranscriptCorrection(slug: string): Promise<TranscriptResponse> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/transcript/redo`,
    { method: "POST" },
  ));
}

export async function listActiveRegens(slug: string): Promise<{ runs: RegenRunSummary[] }> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/regen?active_only=true`,
  ));
}

export async function listRecentRegens(slug: string): Promise<{ runs: RegenRunSummary[] }> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/regen`,
  ));
}

export async function audioTranscribe(
  slug: string, opts: { force: boolean },
): Promise<{ run_id: number; status: string }> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/audio-transcribe?force=${opts.force}`,
    { method: "POST" },
  ));
}

export async function selectTake(
  slug: string, idx: number, takeId: number,
  artefactKind: "keyframe" | "clip",
): Promise<Scene> {
  const body: Record<string, unknown> =
    artefactKind === "keyframe"
      ? { selected_keyframe_take_id: takeId, selection_pinned: true }
      : { selected_clip_take_id: takeId, selection_pinned: true };
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/scenes/${idx}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  ));
}
