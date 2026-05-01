// Story 2 — Preview pane. Audio element is single source of truth for
// playhead. The useAudioPlayback hook (story 13) owns audio events; Preview
// only consumes its outputs and never writes audio.currentTime in response
// to a state change.
import { memo, useCallback, useEffect, useRef } from "react";
import type { Scene, SongDetail } from "../types";
import { assetUrl } from "../format";

// After a user scroll gesture inside the timeline, pause auto-follow for this
// many ms. Matches Storyboard's SCROLL_OVERRIDE_MS so the two panes behave
// consistently.
const TIMELINE_SCROLL_OVERRIDE_MS = 3000;

// Threshold for video resync (story 2 invariant): only nudge the video
// element if it has drifted more than this many seconds from the audio.
const VIDEO_SYNC_DRIFT_S = 0.35;

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

type PreviewProps = {
  song: SongDetail;
  audioRef: React.RefObject<HTMLAudioElement | null>;
  playingSceneIdx: number | null;
  loopEnabled: boolean;
  onLoopEnabledChange: (enabled: boolean) => void;
  onSeekToScene: (idx: number) => void;
};

export default function Preview({
  song, audioRef, playingSceneIdx, loopEnabled, onLoopEnabledChange,
  onSeekToScene,
}: PreviewProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const thumbRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const lastTimelineUserScrollAt = useRef<number>(0);

  const audioSrc = assetUrl(song.audio_path);

  // viewerScene is derived from props. No state. The hook decides which
  // scene is "playing"; Preview just renders it.
  const viewerScene =
    (playingSceneIdx != null
      ? song.scenes.find(s => s.index === playingSceneIdx)
      : undefined) ?? song.scenes[0] ?? null;

  // Video sync: when a clip is selected, drive the <video> element from the
  // audio's currentTime via requestAnimationFrame while audio is playing.
  // This keeps video aligned without subscribing the React tree to
  // timeupdate events.
  useEffect(() => {
    const a = audioRef.current;
    const v = videoRef.current;
    if (!a || !v || !viewerScene?.selected_clip_path) return;
    let rafId: number | null = null;
    let running = false;
    const tick = () => {
      const audioEl = audioRef.current;
      const videoEl = videoRef.current;
      if (!audioEl || !videoEl) { running = false; return; }
      const offset = Math.max(0, audioEl.currentTime - viewerScene.start_s);
      if (videoEl.readyState >= 1 && Math.abs(videoEl.currentTime - offset) > VIDEO_SYNC_DRIFT_S) {
        videoEl.currentTime = Math.max(
          0,
          Math.min(offset, (videoEl.duration || viewerScene.target_duration_s) - 0.01),
        );
      }
      if (!audioEl.paused && videoEl.paused) videoEl.play().catch(() => {});
      if (audioEl.paused && !videoEl.paused) videoEl.pause();
      if (running) rafId = requestAnimationFrame(tick);
    };
    const onPlay = () => {
      if (running) return;
      running = true;
      rafId = requestAnimationFrame(tick);
    };
    const onPause = () => {
      running = false;
      if (rafId != null) cancelAnimationFrame(rafId);
      rafId = null;
      // One last sync pass so video lands cleanly on pause.
      tick();
    };
    a.addEventListener("play", onPlay);
    a.addEventListener("pause", onPause);
    a.addEventListener("seeked", tick);
    // If audio is already playing when the effect mounts (e.g. clip just got
    // selected mid-song), kick the loop off immediately.
    if (!a.paused) onPlay();
    else tick();
    return () => {
      a.removeEventListener("play", onPlay);
      a.removeEventListener("pause", onPause);
      a.removeEventListener("seeked", tick);
      running = false;
      if (rafId != null) cancelAnimationFrame(rafId);
    };
  }, [audioRef, viewerScene?.selected_clip_path, viewerScene?.start_s, viewerScene?.target_duration_s]);

  const handleThumbnailClick = useCallback((s: Scene) => {
    onSeekToScene(s.index);
  }, [onSeekToScene]);

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
            {viewerScene.beat ? <div className="meta">Visual beat: {viewerScene.beat}</div> : null}
          </div>
        ) : null}
      </div>

      <div className="audio-bar">
        <button
          type="button"
          className={`audio-control-btn loop-toggle${loopEnabled ? " pressed" : ""}`}
          onClick={() => onLoopEnabledChange(!loopEnabled)}
          aria-label="Loop selected scene"
          aria-pressed={loopEnabled}
          title="Loop selected scene"
        >
          ↻
        </button>
        <audio ref={audioRef} src={audioSrc} controls preload="auto" />
      </div>

      <div className="timeline" ref={timelineRef}>
        {song.scenes.map(scene => (
          <Thumbnail
            key={scene.index}
            scene={scene}
            current={scene.index === viewerScene?.index}
            onClick={() => handleThumbnailClick(scene)}
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
