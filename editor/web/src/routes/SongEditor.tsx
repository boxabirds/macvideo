// The storyboard editor for one song. Composes preview (story 2), storyboard
// (story 3), pipeline panel (story 9), top bar (stories 4, 8, 10), and split
// pane (story 6).
import { useCallback, useMemo } from "react";
import { useNavigate, useParams } from "react-router";
import useSWR from "swr";
import type { KeyedMutator } from "swr";
import { fetcher } from "../api";
import type { Scene, SongDetail } from "../types";
import TopBar from "../components/TopBar";
import SplitPane from "../components/SplitPane";
import Storyboard from "../components/Storyboard";
import Preview from "../components/Preview";
import PipelinePanel from "../components/PipelinePanel";
import { useAudioPlayback } from "../hooks/useAudioPlayback";
import { useRegenRuns } from "../hooks/useRegenRuns";

const EMPTY_CAMERA_INTENTS: string[] = [];

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
  mutate: KeyedMutator<SongDetail>;
  onBack: () => void;
}) {
  const { data: intents } = useSWR<{ values: string[] }>(
    "/api/camera-intents", fetcher,
  );
  const refreshSong = useCallback(() => {
    void mutate();
  }, [mutate]);
  const { runs: regenRuns, activeRegens } = useRegenRuns(song.slug, refreshSong);

  // Single source of truth for "what scene is playing" — the audio element.
  // useAudioPlayback owns the audio events and exposes playingSceneIdx +
  // seekToScene. Storyboard click → seekToScene; no separate currentIdx state.
  const {
    audioRef,
    playingSceneIdx,
    loopEnabled,
    setLoopEnabled,
    seekToScene,
    seekTo,
  } = useAudioPlayback({
    scenes: song.scenes,
  });

  const onScenePatched = useCallback((idx: number, updated: Scene) => {
    void mutate(current => {
      if (!current) return current;
      const nextScenes = current.scenes.map(s => s.index === idx ? updated : s);
      return { ...current, scenes: nextScenes };
    }, { revalidate: false });
  }, [mutate]);

  const onSongUpdate = useCallback((updated: SongDetail) => {
    void mutate(updated, { revalidate: false });
  }, [mutate]);

  const status = useMemo(() => {
    let keyframesDone = 0;
    let clipsDone = 0;
    for (const scene of song.scenes) {
      if (scene.selected_keyframe_path) keyframesDone += 1;
      if (scene.selected_clip_path) clipsDone += 1;
    }
    return {
      transcription: song.scenes.length > 0 ? "done" as const : "empty" as const,
      world_brief: song.world_brief ? "done" as const : "empty" as const,
      storyboard: song.sequence_arc ? "done" as const : "empty" as const,
      keyframes_done: keyframesDone,
      keyframes_total: song.scenes.length,
      clips_done: clipsDone,
      clips_total: song.scenes.length,
      final: "empty" as const,
    };
  }, [song.scenes, song.sequence_arc, song.world_brief]);

  return (
    <div className="app">
      <TopBar
        song={song}
        onSongUpdate={onSongUpdate}
        onBack={onBack}
      />
      <PipelinePanel
        song={song}
        status={status}
        regenRuns={regenRuns}
        onSongUpdate={onSongUpdate}
      />
      <SplitPane
        left={
          <Storyboard
            song={song}
            cameraIntents={intents?.values ?? EMPTY_CAMERA_INTENTS}
            playingSceneIdx={playingSceneIdx}
            onSeekToScene={seekToScene}
            onSeekToTime={seekTo}
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
