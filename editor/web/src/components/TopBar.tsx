// Top bar: song identity + current visual language + quality-mode control.
// Visual-language changes belong to the world stage, not independent controls.
import { useCallback, useState } from "react";
import type { QualityMode, SongDetail } from "../types";
import { patchSong } from "../api";

type Props = {
  song: SongDetail;
  onSongUpdate: (s: SongDetail) => void;
  onBack: () => void;
};

export default function TopBar({ song, onSongUpdate, onBack }: Props) {
  const [pendingQualityMode, setPendingQualityMode] = useState<null | { newValue: QualityMode }>(null);

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
  const visualLanguage = song.filter == null || song.abstraction == null
    ? "visual language: unset"
    : `visual language: ${song.filter} · abstraction ${song.abstraction}`;

  return (
    <>
      <div className="topbar">
        <button onClick={onBack} className="pill" aria-label="Back to song browser">
          ← songs
        </button>
        <h1>{song.slug}</h1>
        <span className="pill" title="Change this from the world description stage">
          {visualLanguage}
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
