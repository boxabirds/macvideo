// Thin fetch wrapper + SWR fetcher + mutation helpers.
import type { Scene, Song, SongDetail, QualityMode } from "./types";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
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
  created_at: number;
  quality_mode: string | null;
  is_selected: boolean;
};

export async function listTakes(slug: string, idx: number): Promise<{ takes: SceneTake[] }> {
  return handle(await fetch(
    `/api/songs/${encodeURIComponent(slug)}/scenes/${idx}/takes`,
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
