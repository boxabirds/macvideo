// Hook for managing filter changes with backend-derived kind classification.
// Fetches preview estimates from /preview-change endpoint and tracks the kind
// (fresh-setup, destructive, noop). Uses the backend's classification rather than
// duplicating the logic in React, ensuring the preview estimates always match the
// actual PATCH behavior.

import { useCallback, useEffect, useState } from "react";
import type { ChainPreview } from "../api";
import { previewChange, patchSong } from "../api";
import type { SongDetail } from "../types";


type FilterChangeState = {
  kind: "fresh-setup" | "destructive" | "noop";
  preview: ChainPreview | null;
  previewError: string | null;
  inFlight: boolean;
};


export function useFilterChange(song: SongDetail, newFilter: string | null) {
  const [state, setState] = useState<FilterChangeState>({
    kind: "destructive",
    preview: null,
    previewError: null,
    inFlight: false,
  });

  // Determine kind and fetch preview on newFilter change.
  useEffect(() => {
    // No-op if filter hasn't changed.
    if (newFilter === null || newFilter === song.filter) {
      setState((prev) => ({ ...prev, kind: "noop" }));
      return;
    }

    // Check fresh-setup condition: filter=None, world_brief=None, no scenes.
    const isFresh =
      song.filter == null &&
      song.world_brief == null &&
      song.scenes.length === 0;

    if (isFresh) {
      // Fresh-setup: no preview call needed.
      setState((prev) => ({
        ...prev,
        kind: "fresh-setup",
        preview: null,
        previewError: null,
      }));
      return;
    }

    // Destructive: fetch preview.
    let cancelled = false;
    setState((prev) => ({
      ...prev,
      kind: "destructive",
      inFlight: true,
    }));

    previewChange(song.slug, { filter: newFilter })
      .then((p) => {
        if (!cancelled) {
          setState((prev) => ({
            ...prev,
            kind: p.kind,
            preview: p,
            previewError: null,
            inFlight: false,
          }));
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setState((prev) => ({
            ...prev,
            preview: null,
            previewError: String(e),
            inFlight: false,
          }));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [newFilter, song.filter, song.world_brief, song.scenes.length, song.slug]);

  // Apply the filter change.
  const apply = useCallback(async () => {
    if (!newFilter) {
      throw new Error("no filter selected");
    }
    const updated = await patchSong(song.slug, { filter: newFilter });
    return updated;
  }, [newFilter, song.slug]);

  return {
    ...state,
    apply,
  };
}
