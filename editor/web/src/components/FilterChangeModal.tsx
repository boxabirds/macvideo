// Filter change confirmation modal with kind-driven branching.
// Renders "Set filter" setup modal for fresh-setup kinds, "Confirm filter change"
// destructive modal for others. Keeps the logic unified while the copy adapts to
// the song's state.

import type { SongDetail } from "../types";
import type { ChainPreview } from "../api";


type FilterChangeModalProps = {
  song: SongDetail;
  kind: "fresh-setup" | "destructive" | "noop";
  newFilter: string;
  preview: ChainPreview | null;
  previewError: string | null;
  inFlight: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};


export default function FilterChangeModal({
  song, kind, newFilter, preview, previewError, inFlight, onConfirm, onCancel,
}: FilterChangeModalProps) {
  // Noop: no change needed, no modal.
  if (kind === "noop") {
    return null;
  }

  const currentFilter = song.filter ?? "(unset)";
  const clipCount = song.scenes.filter((s) => s.selected_clip_path).length;
  const sceneCount = song.scenes.length;

  if (kind === "fresh-setup") {
    // Setup modal: friendly "Set filter" copy without destructive language.
    return (
      <div className="dialog-backdrop" role="dialog" aria-modal="true">
        <div className="dialog">
          <h2>Set filter</h2>
          <div className="body">
            <p>
              Setting filter to <b>{newFilter}</b> will start the pipeline —
              world description, then storyboard, then scene prompts. You can
              regenerate or edit any of these later.
            </p>
            <dl>
              <dt>Estimated cost</dt>
              <dd>~2 Gemini calls · ~$0.01</dd>
            </dl>
          </div>
          <div className="actions">
            <button onClick={onCancel}>Cancel</button>
            <button className="primary" onClick={onConfirm}>
              Set filter
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Destructive modal: full cost/scope breakdown.
  const cost = inFlight
    ? "computing estimate…"
    : preview
      ? `~${preview.estimate.gemini_calls} Gemini calls · ~$${preview.estimate.estimated_usd.toFixed(2)}`
      : "";
  const time = inFlight
    ? ""
    : preview
      ? `~${Math.round(preview.estimate.estimated_seconds / 60)} min (${preview.estimate.confidence} confidence)`
      : "";
  const scope = inFlight
    ? ""
    : preview
      ? `World description, storyboard, ${preview.scope.scenes_with_new_prompts} image prompts, ${preview.scope.keyframes_to_generate} keyframes`
      : `World description, storyboard, ${sceneCount} image prompts, ${sceneCount} keyframes`;
  const conflict = preview?.would_conflict_with;

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <div className="dialog">
        <h2>Confirm filter change</h2>
        <div className="body">
          <p>
            Changing the filter from <b>{currentFilter}</b> to <b>{newFilter}</b>.
          </p>
          <dl>
            <dt>Regenerate</dt>
            <dd>{scope}</dd>
            <dt>Estimated cost</dt>
            <dd>{cost}</dd>
            <dt>Estimated time</dt>
            <dd>{time}</dd>
            <dt>Clip takes</dt>
            <dd>{clipCount} existing clips will be marked stale but preserved as takes</dd>
          </dl>
          {previewError ? (
            <p style={{ color: "#e06060" }}>Preview failed: {previewError}</p>
          ) : null}
          {conflict ? (
            <p style={{ color: "#e06060" }}>
              ⚠️ Another chain is already running (run #{conflict.run_id}).
              {" "}{conflict.reason}
            </p>
          ) : null}
          <p style={{ color: "var(--text-dim)", fontSize: 12 }}>
            Note: clip re-rendering is NOT automatic — trigger it per scene or from the final-video action.
          </p>
        </div>
        <div className="actions">
          <button onClick={onCancel}>Cancel</button>
          <button
            className="primary"
            onClick={onConfirm}
            disabled={!!conflict}
          >
            Apply change
          </button>
        </div>
      </div>
    </div>
  );
}
