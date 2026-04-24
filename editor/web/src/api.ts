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
