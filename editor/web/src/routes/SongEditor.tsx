// The storyboard editor for one song. Composes preview (story 2), storyboard
// (story 3), pipeline panel (story 9), top bar (stories 4, 8, 10), and split
// pane (story 6).
import { useCallback, useMemo } from "react";
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
import { useAudioPlayback } from "../hooks/useAudioPlayback";

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

  if (error) return <div className="error-card">Could not load song: {String(error)}</div>;
  if (!song) return <div className="empty-state">Loading…</div>;

  return <SongEditorInner song={song} mutate={mutate} onBack={() => navigate("/")} />;
}

// Inner component receives a guaranteed-loaded song. This lets useAudioPlayback
// (which subscribes to the audio element via ref) mount only once Preview's
// <audio> element exists, so the subscription effect attaches on first commit
// rather than skipping with a null ref.
function SongEditorInner({
  song, mutate, onBack,
}: {
  song: SongDetail;
  mutate: (next: SongDetail, opts?: { revalidate?: boolean }) => void;
  onBack: () => void;
}) {
  const { data: intents } = useSWR<{ values: string[] }>(
    "/api/camera-intents", fetcher,
  );
  // Poll /regen so the UI can show in-flight keyframe/clip regens AND the
  // most recent failed stage runs (used by PipelinePanel's transcribe row).
  // Single poll feeds both Storyboard (active scenes) and PipelinePanel
  // (transcribe state) so we don't add a second request.
  const { data: regenRunsResponse } = useSWR<{ runs: RegenRunSummary[] }>(
    `/api/songs/${song.slug}/regen`,
    fetcher,
    { refreshInterval: ACTIVE_REGEN_POLL_MS },
  );

  const regenRuns = regenRunsResponse?.runs ?? [];

  const activeRegens = useMemo<ActiveRegensMap>(() => {
    const map: ActiveRegensMap = {};
    for (const r of regenRuns) {
      if (r.status !== "pending" && r.status !== "running") continue;
      if (r.scene_index == null || r.artefact_kind == null) continue;
      if (r.artefact_kind !== "keyframe" && r.artefact_kind !== "clip") continue;
      const set = map[r.scene_index] ?? new Set<ActiveArtefacts>();
      set.add(r.artefact_kind);
      map[r.scene_index] = set;
    }
    return map;
  }, [regenRuns]);

  // Single source of truth for "what scene is playing" — the audio element.
  // useAudioPlayback owns the audio events and exposes playingSceneIdx +
  // seekToScene. Storyboard click → seekToScene; no separate currentIdx state.
  const {
    audioRef,
    playingSceneIdx,
    loopEnabled,
    setLoopEnabled,
    seekToScene,
  } = useAudioPlayback({
    scenes: song.scenes,
  });

  const onScenePatched = useCallback((idx: number, updated: Scene) => {
    const nextScenes = song.scenes.map(s => s.index === idx ? updated : s);
    mutate({ ...song, scenes: nextScenes }, { revalidate: false });
  }, [song, mutate]);

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
        onBack={onBack}
      />
      <PipelinePanel
        song={song}
        status={status}
        regenRuns={regenRuns}
        onSongUpdate={s => mutate(s, { revalidate: false })}
      />
      <SplitPane
        left={
          <Storyboard
            song={song}
            cameraIntents={intents?.values ?? []}
            playingSceneIdx={playingSceneIdx}
            onSeekToScene={seekToScene}
            onPatch={onScenePatched}
            activeRegens={activeRegens}
          />
        }
        right={
          <Preview
            song={song}
            audioRef={audioRef}
            playingSceneIdx={playingSceneIdx}
            loopEnabled={loopEnabled}
            onLoopEnabledChange={setLoopEnabled}
            onSeekToScene={seekToScene}
          />
        }
      />
    </div>
  );
}
