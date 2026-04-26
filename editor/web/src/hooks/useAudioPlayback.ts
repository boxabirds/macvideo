import { useCallback, useEffect, useRef, useState } from "react";
import type { Scene } from "../types";
import { findSceneAt } from "../lib/scenes";

export type UseAudioPlaybackResult = {
  audioRef: React.RefObject<HTMLAudioElement | null>;
  playingSceneIdx: number | null;
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

  // Stash scenes in a ref so the audio-event handler always reads the latest
  // value without re-subscribing on every scenes-array identity change.
  const scenesRef = useRef(scenes);
  scenesRef.current = scenes;

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const onAudioEvent = () => {
      playheadRef.current = a.currentTime;
      const s = findSceneAt(scenesRef.current, a.currentTime);
      const nextIdx = s?.index ?? null;
      // Functional setState so we compare against the latest committed value
      // without subscribing the effect to playingSceneIdx.
      setPlayingSceneIdx(prev => (prev === nextIdx ? prev : nextIdx));
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
    a.currentTime = timeSeconds;
  }, []);

  const seekToScene = useCallback((idx: number) => {
    const a = audioRef.current;
    if (!a) return;
    const s = scenesRef.current.find(x => x.index === idx);
    if (!s) return;
    a.currentTime = s.start_s;
  }, []);

  return { audioRef, playingSceneIdx, seekToScene, seekTo };
}
