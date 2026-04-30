// Top bar: song identity + filter / abstraction / quality-mode controls
// (stories 4 and 8). Filter changes use FilterChangeModal branched on kind.
// Abstraction + quality_mode changes use inline confirmation logic.
import { useCallback, useEffect, useState } from "react";
import type { QualityMode, SongDetail } from "../types";
import { patchSong, previewChange } from "../api";
import FilterChangeModal from "./FilterChangeModal";
import { useFilterChange } from "../hooks/useFilterChange";

const FILTER_OPTIONS = [
  "oil impasto", "mosaic", "stained glass", "claymation", "watercolour",
  "papercut", "charcoal", "scratchboard", "risograph", "cyanotype", "sumi-e",
  "daguerreotype", "embroidery", "double exposure", "baroque chiaroscuro",
  "surrealist",
] as const;

const ABSTRACTION_STOPS = [0, 25, 50, 75, 100];

type Props = {
  song: SongDetail;
  onSongUpdate: (s: SongDetail) => void;
  onBack: () => void;
};

export default function TopBar({ song, onSongUpdate, onBack }: Props) {
  const [pendingFilter, setPendingFilter] = useState<string | null>(null);
  const [pendingAbstraction, setPendingAbstraction] = useState<null | { newValue: number }>(null);
  const [pendingQualityMode, setPendingQualityMode] = useState<null | { newValue: QualityMode }>(null);

  const filterChange = useFilterChange(song, pendingFilter);

  // Noop changes require no confirmation—dismiss immediately.
  useEffect(() => {
    if (filterChange.kind === "noop") {
      setPendingFilter(null);
    }
  }, [filterChange.kind]);

  const confirmFilter = useCallback(async () => {
    if (!pendingFilter) return;
    try {
      const updated = await filterChange.apply();
      onSongUpdate(updated);
      setPendingFilter(null);
    } catch (e) {
      alert(`Failed to update filter: ${String(e)}`);
      setPendingFilter(null);
    }
  }, [pendingFilter, filterChange, onSongUpdate]);

  const cancelFilter = useCallback(() => setPendingFilter(null), []);

  const confirmAbstraction = useCallback(async () => {
    if (!pendingAbstraction) return;
    try {
      const updated = await patchSong(song.slug, { abstraction: pendingAbstraction.newValue });
      onSongUpdate(updated);
      setPendingAbstraction(null);
    } catch (e) {
      alert(`Failed to update abstraction: ${String(e)}`);
      setPendingAbstraction(null);
    }
  }, [pendingAbstraction, song.slug, onSongUpdate]);

  const cancelAbstraction = useCallback(() => setPendingAbstraction(null), []);

  const confirmQualityMode = useCallback(async () => {
    if (!pendingQualityMode) return;
    try {
      const updated = await patchSong(song.slug, { quality_mode: pendingQualityMode.newValue });
      onSongUpdate(updated);
      setPendingQualityMode(null);
    } catch (e) {
      alert(`Failed to update quality mode: ${String(e)}`);
      setPendingQualityMode(null);
    }
  }, [pendingQualityMode, song.slug, onSongUpdate]);

  const cancelQualityMode = useCallback(() => setPendingQualityMode(null), []);

  const sceneCount = song.scenes.length;
  const clipCount = song.scenes.filter(s => s.selected_clip_path).length;

  return (
    <>
      <div className="topbar">
        <button onClick={onBack} className="pill" aria-label="Back to song browser">
          ← songs
        </button>
        <h1>{song.slug}</h1>
        <span className="pill">
          filter:{" "}
          <select
            value={song.filter ?? ""}
            onChange={e => setPendingFilter(e.target.value || null)}
            style={{ background: "transparent", color: "inherit", border: "none", font: "inherit" }}
          >
            <option value="">(unset)</option>
            {FILTER_OPTIONS.map(f => <option key={f} value={f}>{f}</option>)}
          </select>
        </span>
        <span className="pill">
          abstraction:{" "}
          <select
            value={song.abstraction ?? ""}
            onChange={e => setPendingAbstraction({ newValue: Number(e.target.value) })}
            style={{ background: "transparent", color: "inherit", border: "none", font: "inherit" }}
          >
            {ABSTRACTION_STOPS.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </span>
        <span className="pill">
          mode:{" "}
          <select
            value={song.quality_mode}
            onChange={e => setPendingQualityMode({ newValue: e.target.value as QualityMode })}
            style={{ background: "transparent", color: "inherit", border: "none", font: "inherit" }}
          >
            <option value="draft">Draft 512p/24</option>
            <option value="final">Final 1080p/30</option>
          </select>
        </span>
        <span className="pill info">
          {clipCount}/{sceneCount} clips ready
        </span>
      </div>

      {pendingFilter ? (
        <FilterChangeModal
          song={song}
          kind={filterChange.kind}
          newFilter={pendingFilter}
          preview={filterChange.preview}
          previewError={filterChange.previewError}
          inFlight={filterChange.inFlight}
          onConfirm={confirmFilter}
          onCancel={cancelFilter}
        />
      ) : null}

      {pendingAbstraction ? (
        <ConfirmationModalAbstraction
          song={song}
          newValue={pendingAbstraction.newValue}
          sceneCount={sceneCount}
          clipCount={clipCount}
          onConfirm={confirmAbstraction}
          onCancel={cancelAbstraction}
        />
      ) : null}

      {pendingQualityMode ? (
        <ConfirmationModalQualityMode
          clipCount={clipCount}
          onConfirm={confirmQualityMode}
          onCancel={cancelQualityMode}
        />
      ) : null}
    </>
  );
}

// Abstraction change confirmation modal (inline, not using FilterChangeModal).
function ConfirmationModalAbstraction({
  song, newValue, sceneCount, clipCount, onConfirm, onCancel,
}: {
  song: SongDetail;
  newValue: number;
  sceneCount: number;
  clipCount: number;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const currentAbstraction = song.abstraction ?? "(unset)";

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <div className="dialog">
        <h2>Confirm abstraction change</h2>
        <div className="body">
          <p>Changing the abstraction from <b>{currentAbstraction}</b> to <b>{newValue}</b>.</p>
          <dl>
            <dt>Regenerate</dt>
            <dd>World description, storyboard, {sceneCount} image prompts, {sceneCount} keyframes</dd>
            <dt>Estimated cost</dt>
            <dd>computing estimate…</dd>
            <dt>Estimated time</dt>
            <dd></dd>
            <dt>Clip takes</dt>
            <dd>{clipCount} existing clips will be marked stale but preserved as takes</dd>
          </dl>
          <p style={{ color: "var(--text-dim)", fontSize: 12 }}>
            Note: clip re-rendering is NOT automatic — trigger it per scene or from the final-video action.
          </p>
        </div>
        <div className="actions">
          <button onClick={onCancel}>Cancel</button>
          <button className="primary" onClick={onConfirm}>Apply change</button>
        </div>
      </div>
    </div>
  );
}

// Quality mode change confirmation modal (inline, no chain trigger).
function ConfirmationModalQualityMode({
  clipCount, onConfirm, onCancel,
}: {
  clipCount: number;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <div className="dialog">
        <h2>Confirm quality mode change</h2>
        <div className="body">
          <p>This will mark existing clips as stale and re-render them at the new quality.</p>
          <dl>
            <dt>Cost</dt>
            <dd>No Gemini calls</dd>
            <dt>Time</dt>
            <dd>Instant (rendered clips preserved as takes)</dd>
            <dt>Clip takes</dt>
            <dd>Mark existing {clipCount} clip takes as stale (preserved)</dd>
          </dl>
        </div>
        <div className="actions">
          <button onClick={onCancel}>Cancel</button>
          <button className="primary" onClick={onConfirm}>Apply change</button>
        </div>
      </div>
    </div>
  );
}
