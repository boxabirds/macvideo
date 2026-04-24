// The storyboard editor for one song. Composes preview (story 2), storyboard
// (story 3), pipeline panel (story 9), top bar (stories 4, 8, 10), and split
// pane (story 6).
import { useCallback, useState } from "react";
import { useNavigate, useParams } from "react-router";
import useSWR from "swr";
import { fetcher } from "../api";
import type { Scene, SongDetail } from "../types";
import TopBar from "../components/TopBar";
import SplitPane from "../components/SplitPane";
import Storyboard from "../components/Storyboard";
import Preview from "../components/Preview";
import PipelinePanel from "../components/PipelinePanel";

export default function SongEditor() {
  const { slug = "" } = useParams();
  const navigate = useNavigate();
  const { data: song, error, mutate } = useSWR<SongDetail>(
    slug ? `/api/songs/${slug}` : null, fetcher,
  );
  const { data: intents } = useSWR<{ values: string[] }>(
    "/api/camera-intents", fetcher,
  );

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
      <PipelinePanel song={song} status={status} />
      <SplitPane
        left={
          <Storyboard
            song={song}
            cameraIntents={intents?.values ?? []}
            currentIdx={currentIdx}
            onSelect={setCurrentIdx}
            onPatch={onScenePatched}
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
