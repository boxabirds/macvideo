import { useCallback, useEffect, useRef, useState } from "react";
import type { Scene } from "../types";
import { findSceneAt } from "../lib/scenes";

export type UseAudioPlaybackResult = {
  audioRef: React.RefObject<HTMLAudioElement | null>;
  playingSceneIdx: number | null;
  loopEnabled: boolean;
  setLoopEnabled: (enabled: boolean) => void;
  togglePlay: () => void;
  stop: () => void;
  seekToScene: (idx: number) => void;
  seekTo: (timeSeconds: number) => void;
};

export function useAudioPlayback(args: { scenes: Scene[] }): UseAudioPlaybackResult {
  const { scenes } = args;
  const audioRef = useRef<HTMLAudioElement>(null);
  const playheadRef = useRef<number>(0);
  const [playingSceneIdx, setPlayingSceneIdx] = useState<number | null>(
    scenes[0]?.index ?? null,
  );
  const playingSceneIdxRef = useRef<number | null>(scenes[0]?.index ?? null);
  const selectedSceneIdxRef = useRef<number | null>(scenes[0]?.index ?? null);
  const loopEnabledRef = useRef(true);
  const [loopEnabled, setLoopEnabledState] = useState(true);

  // Stash scenes in a ref so the audio-event handler always reads the latest
  // value without re-subscribing on every scenes-array identity change.
  const scenesRef = useRef(scenes);
  scenesRef.current = scenes;

  const setLoopEnabled = useCallback((enabled: boolean) => {
    loopEnabledRef.current = enabled;
    setLoopEnabledState(enabled);
  }, []);

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const onAudioEvent = () => {
      playheadRef.current = a.currentTime;
      const selectedIdx = selectedSceneIdxRef.current;
      const selected = scenesRef.current.find(s => s.index === selectedIdx);
      if (
        loopEnabledRef.current
        && selected
        && !a.paused
        && a.currentTime >= selected.end_s
      ) {
        a.currentTime = selected.start_s;
        setPlayingSceneIdx(prev => {
          playingSceneIdxRef.current = selected.index;
          return prev === selected.index ? prev : selected.index;
        });
        void a.play().catch(() => {});
        return;
      }
      const s = findSceneAt(scenesRef.current, a.currentTime);
      const nextIdx = s?.index ?? null;
      // Functional setState so we compare against the latest committed value
      // without subscribing the effect to playingSceneIdx.
      setPlayingSceneIdx(prev => {
        playingSceneIdxRef.current = nextIdx;
        return prev === nextIdx ? prev : nextIdx;
      });
    };
    a.addEventListener("timeupdate", onAudioEvent);
    a.addEventListener("seeked", onAudioEvent);
    a.addEventListener("play", onAudioEvent);
    a.addEventListener("pause", onAudioEvent);
    return () => {
      a.removeEventListener("timeupdate", onAudioEvent);
      a.removeEventListener("seeked", onAudioEvent);
      a.removeEventListener("play", onAudioEvent);
      a.removeEventListener("pause", onAudioEvent);
    };
  }, []);

  const seekTo = useCallback((timeSeconds: number) => {
    const a = audioRef.current;
    if (!a) return;
    const s = findSceneAt(scenesRef.current, timeSeconds);
    if (s) {
      selectedSceneIdxRef.current = s.index;
      setPlayingSceneIdx(prev => {
        playingSceneIdxRef.current = s.index;
        return prev === s.index ? prev : s.index;
      });
    }
    a.currentTime = timeSeconds;
  }, []);

  const seekToScene = useCallback((idx: number) => {
    const a = audioRef.current;
    if (!a) return;
    const s = scenesRef.current.find(x => x.index === idx);
    if (!s) return;
    selectedSceneIdxRef.current = idx;
    if (!a.paused && playingSceneIdxRef.current === idx) return;
    a.currentTime = s.start_s;
  }, []);

  const togglePlay = useCallback(() => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) {
      void a.play().catch(() => {});
    } else {
      a.pause();
    }
  }, []);

  const stop = useCallback(() => {
    const a = audioRef.current;
    if (!a) return;
    a.pause();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.altKey || event.code !== "Space") return;
      const target = event.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName?.toLowerCase();
        if (tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable) {
          return;
        }
      }
      event.preventDefault();
      togglePlay();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [togglePlay]);

  return {
    audioRef,
    playingSceneIdx,
    loopEnabled,
    setLoopEnabled,
    togglePlay,
    stop,
    seekToScene,
    seekTo,
  };
}
