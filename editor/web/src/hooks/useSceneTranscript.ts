import { useCallback } from "react";
import useSWR from "swr";
import { getSceneTranscript, type TranscriptResponse } from "../api";

export type SceneTranscriptKey = readonly ["scene-transcript", string, number, string];

export function sceneTranscriptKey(
  slug: string,
  sceneIndex: number,
  sourceText: string,
  enabled: boolean,
): SceneTranscriptKey | null {
  return enabled ? ["scene-transcript", slug, sceneIndex, sourceText] as const : null;
}

function fetchSceneTranscript([, slug, sceneIndex]: SceneTranscriptKey) {
  return getSceneTranscript(slug, sceneIndex);
}

export function useSceneTranscript(
  slug: string,
  sceneIndex: number,
  sourceText: string,
  enabled: boolean,
) {
  const { data, error, isLoading, mutate } = useSWR<TranscriptResponse>(
    sceneTranscriptKey(slug, sceneIndex, sourceText, enabled),
    fetchSceneTranscript,
    { revalidateIfStale: false, revalidateOnFocus: false },
  );

  const setTranscriptResponse = useCallback((next: TranscriptResponse) => (
    mutate(next, { revalidate: false })
  ), [mutate]);

  return {
    words: data?.words ?? null,
    targetText: data?.target_text ?? null,
    error,
    isLoading,
    setTranscriptResponse,
  };
}
