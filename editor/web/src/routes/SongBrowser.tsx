// Story 7 — Song browser: list/grid of songs with per-song status strip.
import { memo, useCallback, useState } from "react";
import { useNavigate } from "react-router";
import useSWR from "swr";
import { fetcher } from "../api";
import type { Song, StageStatus } from "../types";
import { formatBytes, formatDurationMS } from "../format";
import { localGet, localSet } from "../localSetting";

type View = "list" | "grid";

function StatusStrip({ s }: { s: StageStatus }) {
  return (
    <div className="status-strip" role="list">
      <span className={`stage ${s.transcription}`} role="listitem" title="Lyric alignment">align</span>
      <span className={`stage ${s.world_brief}`} role="listitem" title="World description">world</span>
      <span className={`stage ${s.storyboard}`} role="listitem" title="Scene storyboard">story</span>
      <span
        className={`stage ${s.keyframes_done === s.keyframes_total && s.keyframes_total > 0 ? "done" : s.keyframes_done > 0 ? "progress" : "empty"}`}
        role="listitem"
        title={`${s.keyframes_done} of ${s.keyframes_total} keyframes`}
      >
        kf {s.keyframes_done}/{s.keyframes_total}
      </span>
      <span
        className={`stage ${s.clips_done === s.clips_total && s.clips_total > 0 ? "done" : s.clips_done > 0 ? "progress" : "empty"}`}
        role="listitem"
        title={`${s.clips_done} of ${s.clips_total} clips`}
      >
        clip {s.clips_done}/{s.clips_total}
      </span>
      <span className={`stage ${s.final}`} role="listitem" title="Final video">final</span>
    </div>
  );
}

const SongRow = memo(function SongRow({ song, onClick }: { song: Song; onClick: () => void }) {
  return (
    <div className="song-row" onClick={onClick} role="button" tabIndex={0} aria-label={`Open ${song.slug}`}>
      <div>
        <div className="slug">{song.slug}</div>
        <div className="sub">{song.filter ?? "(no filter)"} · abstraction {song.abstraction ?? "—"}</div>
      </div>
      <div className="sub">{formatDurationMS(song.duration_s)}</div>
      <div className="sub">{formatBytes(song.size_bytes)}</div>
      <div className="sub">mode: {song.quality_mode}</div>
      <StatusStrip s={song.status} />
    </div>
  );
});

const SongCard = memo(function SongCard({ song, onClick }: { song: Song; onClick: () => void }) {
  return (
    <div className="song-card" onClick={onClick} role="button" tabIndex={0} aria-label={`Open ${song.slug}`}>
      <div className="slug">{song.slug}</div>
      <div className="sub">{song.filter ?? "(no filter)"} · abstraction {song.abstraction ?? "—"}</div>
      <div className="sub">{formatDurationMS(song.duration_s)} · {formatBytes(song.size_bytes)}</div>
      <StatusStrip s={song.status} />
    </div>
  );
});

export default function SongBrowser() {
  const navigate = useNavigate();
  const [view, setViewRaw] = useState<View>(
    () => localGet<View>("editor.browser.view", 1, "list"),
  );
  const setView = useCallback((v: View) => {
    setViewRaw(v);
    localSet("editor.browser.view", 1, v);
  }, []);

  // Rule: client-swr-dedup + refresh every 60s so background work surfaces.
  const { data, error, isLoading } = useSWR<{ songs: Song[] }>(
    "/api/songs", fetcher, { refreshInterval: 60_000, revalidateOnFocus: true },
  );

  if (error) return <div className="error-card">Failed to load songs: {String(error)}</div>;
  if (isLoading || !data) return <div className="empty-state">Loading songs…</div>;

  if (data.songs.length === 0) {
    return (
      <div className="empty-state">
        <div>No songs found in <code>music/</code>.</div>
        <div style={{ marginTop: 10 }}>
          <button onClick={async () => {
            await fetch("/api/import", { method: "POST" });
            location.reload();
          }}>Scan music folder</button>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="browser-header">
        <h2 style={{ margin: 0, fontSize: 15, color: "#fff", fontWeight: 500 }}>
          {data.songs.length} song{data.songs.length === 1 ? "" : "s"}
        </h2>
        <div className="view-toggle" role="tablist">
          <button
            role="tab"
            aria-selected={view === "list"}
            className={view === "list" ? "active" : ""}
            onClick={() => setView("list")}
          >List</button>
          <button
            role="tab"
            aria-selected={view === "grid"}
            className={view === "grid" ? "active" : ""}
            onClick={() => setView("grid")}
          >Grid</button>
        </div>
      </div>

      {view === "list" ? (
        <div className="song-list">
          {data.songs.map(song => (
            <SongRow key={song.slug} song={song}
              onClick={() => navigate(`/songs/${song.slug}`)} />
          ))}
        </div>
      ) : (
        <div className="song-grid">
          {data.songs.map(song => (
            <SongCard key={song.slug} song={song}
              onClick={() => navigate(`/songs/${song.slug}`)} />
          ))}
        </div>
      )}
    </>
  );
}
