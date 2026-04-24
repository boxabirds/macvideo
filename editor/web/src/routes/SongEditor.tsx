// The storyboard editor for one song. Composes preview (story 2), storyboard
// (story 3), pipeline panel (story 9), top bar (stories 4, 8, 10), and split
// pane (story 6).
import { useCallback, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";
import useSWR from "swr";
import { fetcher } from "../api";
import type { Scene, SongDetail } from "../types";
import type { RegenRunSummary } from "../api";
import TopBar from "../components/TopBar";
import SplitPane from "../components/SplitPane";
import Storyboard from "../components/Storyboard";
import Preview from "../components/Preview";
import PipelinePanel from "../components/PipelinePanel";

// Poll interval for active regens. Short enough that the UI spinner feels
// responsive without hammering the backend for a rarely-changing query.
const ACTIVE_REGEN_POLL_MS = 2000;

export type ActiveArtefacts = "keyframe" | "clip";
export type ActiveRegensMap = Record<number, Set<ActiveArtefacts>>;

export default function SongEditor() {
  const { slug = "" } = useParams();
  const navigate = useNavigate();
  const { data: song, error, mutate } = useSWR<SongDetail>(
    slug ? `/api/songs/${slug}` : null, fetcher,
  );
  const { data: intents } = useSWR<{ values: string[] }>(
    "/api/camera-intents", fetcher,
  );
  // Poll /regen?active_only=true so the UI can show in-flight keyframe/clip
  // regens without wiring SSE. Low-volume endpoint, small rows.
  const { data: activeRegensResponse } = useSWR<{ runs: RegenRunSummary[] }>(
    slug ? `/api/songs/${slug}/regen?active_only=true` : null,
    fetcher,
    { refreshInterval: ACTIVE_REGEN_POLL_MS },
  );

  const activeRegens = useMemo<ActiveRegensMap>(() => {
    const map: ActiveRegensMap = {};
    for (const r of activeRegensResponse?.runs ?? []) {
      if (r.scene_index == null || r.artefact_kind == null) continue;
      if (r.artefact_kind !== "keyframe" && r.artefact_kind !== "clip") continue;
      const set = map[r.scene_index] ?? new Set<ActiveArtefacts>();
      set.add(r.artefact_kind);
      map[r.scene_index] = set;
    }
    return map;
  }, [activeRegensResponse]);

  // Derive a "status" object for the pipeline panel from the song detail.
  const [currentIdx, setCurrentIdx] = useState<number | null>(null);

  const onScenePatched = useCallback((idx: number, updated: Scene) => {
    if (!song) return;
    const nextScenes = song.scenes.map(s => s.index === idx ? updated : s);
    mutate({ ...song, scenes: nextScenes }, { revalidate: false });
  }, [song, mutate]);

  if (error) return <div className="error-card">Could not load song: {String(error)}</div>;
  if (!song) return <div className="empty-state">Loading…</div>;

  const status = {
    transcription: song.scenes.length > 0 ? "done" as const : "empty" as const,
    world_brief: song.world_brief ? "done" as const : "empty" as const,
    storyboard: song.sequence_arc ? "done" as const : "empty" as const,
    keyframes_done: song.scenes.filter(s => s.selected_keyframe_path).length,
    keyframes_total: song.scenes.length,
    clips_done: song.scenes.filter(s => s.selected_clip_path).length,
    clips_total: song.scenes.length,
    final: "empty" as const,
  };

  return (
    <div className="app">
      <TopBar
        song={song}
        onSongUpdate={s => mutate(s, { revalidate: false })}
        onBack={() => navigate("/")}
      />
      <PipelinePanel
        song={song}
        status={status}
        onSongUpdate={s => mutate(s, { revalidate: false })}
      />
      <SplitPane
        left={
          <Storyboard
            song={song}
            cameraIntents={intents?.values ?? []}
            currentIdx={currentIdx}
            onSelect={setCurrentIdx}
            onPatch={onScenePatched}
            activeRegens={activeRegens}
          />
        }
        right={
          <Preview
            song={song}
            currentIdx={currentIdx}
            onSceneChange={setCurrentIdx}
          />
        }
      />
    </div>
  );
}
