import { useCallback } from "react";
import useSWR from "swr";
import { fetcher, type FinishedVideo } from "../api";

const EMPTY_FINISHED: FinishedVideo[] = [];

export function useFinishedVideos(slug: string) {
  const { data, mutate } = useSWR<{ finished: FinishedVideo[] }>(
    slug ? `/api/songs/${encodeURIComponent(slug)}/finished` : null,
    fetcher,
  );
  const reloadFinished = useCallback(async () => {
    await mutate();
  }, [mutate]);

  return {
    finished: data?.finished ?? EMPTY_FINISHED,
    reloadFinished,
  };
}
