// Top bar: song identity + filter / abstraction / quality-mode controls
// (stories 4 and 8). Changes go through the confirmation dialog for stories
// where regen scope matters.
import { useCallback, useState } from "react";
import type { QualityMode, SongDetail } from "../types";
import { patchSong } from "../api";

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
  const [pending, setPending] = useState<null | {
    kind: "filter" | "abstraction" | "quality_mode";
    newValue: string | number;
  }>(null);

  const promptChange = useCallback((kind: "filter" | "abstraction" | "quality_mode", newValue: string | number) => {
    setPending({ kind, newValue });
  }, []);

  const confirm = useCallback(async () => {
    if (!pending) return;
    try {
      const body: any = {};
      body[pending.kind] = pending.newValue;
      const updated = await patchSong(song.slug, body);
      onSongUpdate(updated);
    } catch (e) {
      alert(`Failed to update ${pending.kind}: ${String(e)}`);
    } finally {
      setPending(null);
    }
  }, [pending, song.slug, onSongUpdate]);

  const cancel = useCallback(() => setPending(null), []);

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
            onChange={e => promptChange("filter", e.target.value)}
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
            onChange={e => promptChange("abstraction", Number(e.target.value))}
            style={{ background: "transparent", color: "inherit", border: "none", font: "inherit" }}
          >
            {ABSTRACTION_STOPS.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </span>
        <span className="pill">
          mode:{" "}
          <select
            value={song.quality_mode}
            onChange={e => promptChange("quality_mode", e.target.value as QualityMode)}
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

      {pending ? (
        <ConfirmationModal
          song={song}
          kind={pending.kind}
          newValue={pending.newValue}
          sceneCount={sceneCount}
          clipCount={clipCount}
          onConfirm={confirm}
          onCancel={cancel}
        />
      ) : null}
    </>
  );
}

function ConfirmationModal({
  song, kind, newValue, sceneCount, clipCount, onConfirm, onCancel,
}: {
  song: SongDetail;
  kind: "filter" | "abstraction" | "quality_mode";
  newValue: string | number;
  sceneCount: number;
  clipCount: number;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const labels: Record<typeof kind, [string, string]> = {
    filter: ["filter", song.filter ?? "(unset)"],
    abstraction: ["abstraction", String(song.abstraction ?? "(unset)")],
    quality_mode: ["quality mode", song.quality_mode],
  };
  const [label, from] = labels[kind];
  const isCosmetic = kind === "quality_mode";
  const cost = isCosmetic ? "No Gemini calls" : `~${sceneCount * 2 + 2} Gemini calls · ~$${(sceneCount * 0.04 + 0.05).toFixed(2)}`;
  const time = isCosmetic
    ? "Instant (rendered clips preserved as takes)"
    : `~${Math.round(sceneCount * 0.3)} min of API calls`;

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <div className="dialog">
        <h2>Confirm {label} change</h2>
        <div className="body">
          <p>Changing the {label} from <b>{String(from)}</b> to <b>{String(newValue)}</b>.</p>
          <dl>
            <dt>Regenerate</dt>
            <dd>{isCosmetic
              ? `Mark existing ${clipCount} clip takes as stale (preserved)`
              : `World description, scene storyboard, ${sceneCount} image prompts, ${sceneCount} keyframes`}</dd>
            <dt>Estimated cost</dt>
            <dd>{cost}</dd>
            <dt>Estimated time</dt>
            <dd>{time}</dd>
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
