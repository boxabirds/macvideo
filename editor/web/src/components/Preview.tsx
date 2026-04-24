// Story 2 — Preview pane. Audio element is single source of truth for
// playhead; viewer re-syncs on audio events. Timeline strip of keyframe
// thumbnails drives seek.
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Scene, SongDetail } from "../types";
import { assetUrl } from "../format";

// After a user scroll gesture inside the timeline, pause auto-follow for this
// many ms. Matches Storyboard's SCROLL_OVERRIDE_MS so the two panes behave
// consistently.
const TIMELINE_SCROLL_OVERRIDE_MS = 3000;

function findSceneAt(scenes: Scene[], t: number): Scene | null {
  if (scenes.length === 0) return null;
  for (const s of scenes) {
    if (t >= s.start_s && t < s.end_s) return s;
  }
  // Nearest shot by time — never fall back to the last shot of the song
  // (that was the preview.html bug).
  let best = scenes[0]!;
  let bestDist = Infinity;
  for (const s of scenes) {
    const d = Math.min(Math.abs(t - s.start_s), Math.abs(t - s.end_s));
    if (d < bestDist) { bestDist = d; best = s; }
  }
  return best;
}

const Thumbnail = memo(function Thumbnail({
  scene, current, onClick, thumbRef,
}: {
  scene: Scene;
  current: boolean;
  onClick: () => void;
  thumbRef?: (el: HTMLDivElement | null) => void;
}) {
  const src = scene.selected_keyframe_path ? assetUrl(scene.selected_keyframe_path) : "";
  return (
    <div ref={thumbRef}
         className={`thumb${current ? " current" : ""}`} onClick={onClick}
         title={`#${scene.index} · ${scene.target_text}\n[${scene.start_s.toFixed(1)}s–${scene.end_s.toFixed(1)}s]`}
         role="button">
      {src ? <img src={src} loading="lazy" alt="" /> : null}
      <span className="idx">#{scene.index}</span>
    </div>
  );
});

export default function Preview({
  song, currentIdx, onSceneChange,
}: { song: SongDetail; currentIdx: number | null; onSceneChange?: (idx: number) => void }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const thumbRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const lastTimelineUserScrollAt = useRef<number>(0);
  const [playhead, setPlayhead] = useState(0);
  const [viewerScene, setViewerScene] = useState<Scene | null>(
    song.scenes.length ? song.scenes[0]! : null,
  );

  const audioSrc = useMemo(() => assetUrl(song.audio_path), [song.audio_path]);

  // Audio-event-driven re-sync of viewer state.
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const onTime = () => {
      const t = a.currentTime;
      setPlayhead(t);
      const s = findSceneAt(song.scenes, t);
      if (s && s.index !== viewerScene?.index) {
        setViewerScene(s);
        onSceneChange?.(s.index);
      }
    };
    const onSeeked = () => onTime();
    a.addEventListener("timeupdate", onTime);
    a.addEventListener("seeked", onSeeked);
    a.addEventListener("play", onTime);
    a.addEventListener("pause", onTime);
    return () => {
      a.removeEventListener("timeupdate", onTime);
      a.removeEventListener("seeked", onSeeked);
      a.removeEventListener("play", onTime);
      a.removeEventListener("pause", onTime);
    };
  }, [song.scenes, viewerScene?.index, onSceneChange]);

  // Jump to a scene when the user clicks in the LHS editor.
  useEffect(() => {
    if (currentIdx == null || !audioRef.current) return;
    const s = song.scenes.find(x => x.index === currentIdx);
    if (s && Math.abs(audioRef.current.currentTime - s.start_s) > 0.2) {
      audioRef.current.currentTime = s.start_s;
    }
  }, [currentIdx, song.scenes]);

  // Sync video element to the scene + playhead offset.
  useEffect(() => {
    if (!viewerScene || !videoRef.current) return;
    if (viewerScene.selected_clip_path) {
      const offset = Math.max(0, playhead - viewerScene.start_s);
      const v = videoRef.current;
      if (v.readyState >= 1 && Math.abs(v.currentTime - offset) > 0.35) {
        v.currentTime = Math.max(0, Math.min(offset, (v.duration || viewerScene.target_duration_s) - 0.01));
      }
      if (!audioRef.current?.paused && v.paused) v.play().catch(() => {});
      if (audioRef.current?.paused && !v.paused) v.pause();
    }
  }, [viewerScene, playhead]);

  const onSeekToScene = useCallback((s: Scene) => {
    if (audioRef.current) audioRef.current.currentTime = s.start_s;
  }, []);

  // Track user scroll gestures on the timeline so the auto-follow effect
  // doesn't fight them. Same pattern as Storyboard's scroll-follow.
  useEffect(() => {
    const el = timelineRef.current;
    if (!el) return;
    const onWheel = () => { lastTimelineUserScrollAt.current = Date.now(); };
    el.addEventListener("wheel", onWheel, { passive: true });
    el.addEventListener("touchmove", onWheel, { passive: true });
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchmove", onWheel);
    };
  }, []);

  // Autoscroll the timeline so the current thumbnail stays visible.
  useEffect(() => {
    if (!viewerScene) return;
    const now = Date.now();
    if (now - lastTimelineUserScrollAt.current < TIMELINE_SCROLL_OVERRIDE_MS) return;
    const el = thumbRefs.current.get(viewerScene.index);
    // jsdom doesn't implement scrollIntoView; tests may also not stub it.
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
    }
  }, [viewerScene?.index]);

  const onFullscreen = useCallback(() => {
    const el = document.querySelector<HTMLElement>(".viewer");
    if (!el) return;
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    } else {
      el.requestFullscreen().catch(() => {});
    }
  }, []);

  return (
    <div className="preview">
      <div className="viewer">
        {viewerScene?.selected_clip_path ? (
          <video
            ref={videoRef}
            src={assetUrl(viewerScene.selected_clip_path)}
            muted playsInline
            key={viewerScene.selected_clip_path}
          />
        ) : viewerScene?.selected_keyframe_path && !viewerScene.missing_assets.includes("keyframe") ? (
          <img src={assetUrl(viewerScene.selected_keyframe_path)} alt="" />
        ) : viewerScene ? (
          <div className="placeholder">Scene #{viewerScene.index} — no asset</div>
        ) : (
          <div className="placeholder">No scene at playhead</div>
        )}
        <button className="fs-btn" onClick={onFullscreen}
                aria-label="Toggle full-screen" title="Toggle full-screen">⛶</button>
        {viewerScene ? (
          <div className="caption">
            <div><b>#{viewerScene.index} · {viewerScene.target_text}</b></div>
            <div className="meta">
              [{viewerScene.start_s.toFixed(1)}s – {viewerScene.end_s.toFixed(1)}s] · {viewerScene.kind}
              {viewerScene.camera_intent ? ` · ${viewerScene.camera_intent}` : ""}
            </div>
            {viewerScene.beat ? <div className="meta">{viewerScene.beat}</div> : null}
          </div>
        ) : null}
      </div>

      <div className="audio-bar">
        <audio ref={audioRef} src={audioSrc} controls preload="auto" />
      </div>

      <div className="timeline" ref={timelineRef}>
        {song.scenes.map(scene => (
          <Thumbnail
            key={scene.index}
            scene={scene}
            current={scene.index === viewerScene?.index}
            onClick={() => onSeekToScene(scene)}
            thumbRef={el => {
              if (el) thumbRefs.current.set(scene.index, el);
              else thumbRefs.current.delete(scene.index);
            }}
          />
        ))}
      </div>
    </div>
  );
}
