import { useCallback, useEffect, useMemo, useRef } from "react";
import useSWR from "swr";
import { fetcher, type RegenRunSummary } from "../api";

const ACTIVE_REGEN_POLL_MS = 2000;
const EMPTY_RUNS: RegenRunSummary[] = [];

export type ActiveArtefacts = "keyframe" | "clip";
export type ActiveRegensMap = Record<number, Set<ActiveArtefacts>>;

type RunStatus = RegenRunSummary["status"];

function isTerminal(status: RunStatus): boolean {
  return status === "done" || status === "failed" || status === "cancelled";
}

function runFingerprint(run: RegenRunSummary): string {
  return [
    run.id,
    run.scope,
    run.status,
    run.scene_index ?? "",
    run.artefact_kind ?? "",
    run.ended_at ?? "",
    run.error ?? "",
  ].join(":");
}

function runsFingerprint(runs: RegenRunSummary[]): string {
  return runs.map(runFingerprint).join("|");
}

export function shouldRefreshSongForRegenTransition(
  previousRuns: RegenRunSummary[],
  nextRuns: RegenRunSummary[],
): boolean {
  const previousById = new Map(previousRuns.map(run => [run.id, run]));
  for (const next of nextRuns) {
    const previous = previousById.get(next.id);
    if (!previous) {
      if (isTerminal(next.status)) return true;
      continue;
    }
    if (previous.status !== next.status && isTerminal(next.status)) {
      return true;
    }
    if (previous.ended_at !== next.ended_at && isTerminal(next.status)) {
      return true;
    }
  }
  return false;
}

export function buildActiveRegens(runs: RegenRunSummary[]): ActiveRegensMap {
  const map: ActiveRegensMap = {};
  for (const run of runs) {
    if (run.status !== "pending" && run.status !== "running") continue;
    if (run.scene_index == null || run.artefact_kind == null) continue;
    if (run.artefact_kind !== "keyframe" && run.artefact_kind !== "clip") continue;
    const set = map[run.scene_index] ?? new Set<ActiveArtefacts>();
    set.add(run.artefact_kind);
    map[run.scene_index] = set;
  }
  return map;
}

export function useRegenRuns(
  slug: string,
  onSongContentMayHaveChanged: () => void,
) {
  const { data } = useSWR<{ runs: RegenRunSummary[] }>(
    slug ? `/api/songs/${slug}/regen` : null,
    fetcher,
    { refreshInterval: ACTIVE_REGEN_POLL_MS },
  );
  const runs = data?.runs ?? EMPTY_RUNS;
  const previousRunsRef = useRef<RegenRunSummary[] | null>(null);
  const refresh = useCallback(onSongContentMayHaveChanged, [onSongContentMayHaveChanged]);
  const fingerprint = useMemo(() => runsFingerprint(runs), [runs]);

  useEffect(() => {
    const previousRuns = previousRunsRef.current;
    if (previousRuns && shouldRefreshSongForRegenTransition(previousRuns, runs)) {
      refresh();
    }
    previousRunsRef.current = runs;
  }, [fingerprint, refresh]);

  const activeRegens = useMemo(() => buildActiveRegens(runs), [fingerprint]);

  return { runs, activeRegens };
}
