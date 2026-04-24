// Story 9 — pipeline stage buttons. Each button POSTs to
// /api/songs/:slug/stages/:stage which enqueues a real gen_keyframes.py
// subprocess (or the fake under tests). The user sees DB-derived progress
// on the next SWR revalidation.
import { useCallback, useState } from "react";
import type { SongDetail, StageStatus } from "../types";

// Stage button keys → backend stage-name + done-state computation.
const STAGES = [
  { key: "transcription", label: "lyric alignment",     stageName: "transcribe" },
  { key: "world_brief",   label: "world description",   stageName: "world-brief" },
  { key: "storyboard",    label: "storyboard",          stageName: "storyboard" },
  { key: "image_prompts", label: "image prompts",       stageName: "image-prompts" },
  { key: "keyframes",     label: "keyframes",           stageName: "keyframes" },
] as const;

async function runStage(slug: string, stageName: string, redo: boolean) {
  const r = await fetch(
    `/api/songs/${encodeURIComponent(slug)}/stages/${stageName}?redo=${redo}`,
    { method: "POST" },
  );
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(`${stageName} failed: ${r.status} ${JSON.stringify(body)}`);
  }
  return r.json();
}

export default function PipelinePanel({ song, status }: { song: SongDetail; status: StageStatus }) {
  const [confirm, setConfirm] = useState<null | { stageName: string; isRedo: boolean; label: string }>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // PRD: 'filter and abstraction pickers appear as a one-time dialog the
  // first time the world description is generated'. If either is unset we
  // open the picker before dispatching the world-brief run.
  const [filterPicker, setFilterPicker] = useState<null | { pendingStageName: string; isRedo: boolean }>(null);

  const onClick = useCallback((stageName: string, label: string, isRedo: boolean) => {
    const needsFilterPicker =
      stageName === "world-brief" && (song.filter == null || song.abstraction == null);
    if (needsFilterPicker) {
      setFilterPicker({ pendingStageName: stageName, isRedo });
      return;
    }
    if (isRedo) {
      setConfirm({ stageName, isRedo: true, label });
    } else {
      void trigger(stageName, false);
    }
  }, [song.filter, song.abstraction]);

  const trigger = useCallback(async (stageName: string, isRedo: boolean) => {
    setBusy(stageName);
    setError(null);
    try {
      await runStage(song.slug, stageName, isRedo);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
      setConfirm(null);
    }
  }, [song.slug]);

  return (
    <div className="pipeline-panel" aria-label="Pipeline stages">
      {STAGES.map(stage => {
        let state: string;
        let summary = "";
        if (stage.key === "keyframes") {
          const done = status.keyframes_done;
          const total = status.keyframes_total;
          state = done === total && total > 0 ? "done" : done > 0 ? "progress" : "empty";
          summary = ` (${done}/${total})`;
        } else if (stage.key === "image_prompts") {
          const total = song.scenes.length;
          const withPrompt = song.scenes.filter(s => s.image_prompt).length;
          state = withPrompt === total && total > 0 ? "done" : withPrompt > 0 ? "progress" : "empty";
          summary = ` (${withPrompt}/${total})`;
        } else {
          state = (status as any)[stage.key] ?? "empty";
        }
        const isRedo = state === "done";
        return (
          <div key={stage.key} className={`pipeline-stage ${state}`}>
            <span className="label">{stage.label}{summary}</span>
            <button
              onClick={() => onClick(stage.stageName, stage.label, isRedo)}
              disabled={busy === stage.stageName}
              title={isRedo
                ? `Re-run ${stage.label} (marks downstream stages stale)`
                : `Run ${stage.label}`}
            >
              {busy === stage.stageName ? "…" : (isRedo ? "↻" : "▶")}
            </button>
          </div>
        );
      })}
      {error ? <span className="pipeline-error" style={{ color: "#e06060" }}>{error}</span> : null}

      <RunAllOutstanding slug={song.slug} />

      <RenderFinalAction song={song} status={status} />

      {filterPicker ? (
        <FilterAbstractionPicker
          song={song}
          onCancel={() => setFilterPicker(null)}
          onConfirmed={async (filter, abstraction) => {
            // Persist picks, then dispatch the originally-requested stage.
            try {
              await fetch(
                `/api/songs/${encodeURIComponent(song.slug)}`,
                {
                  method: "PATCH",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ filter, abstraction }),
                },
              );
            } catch {
              // Not fatal for the dialog — stage run will fail loudly.
            }
            const pendingStage = filterPicker.pendingStageName;
            const pendingRedo = filterPicker.isRedo;
            setFilterPicker(null);
            void trigger(pendingStage, pendingRedo);
          }}
        />
      ) : null}

      {confirm ? (
        <div className="dialog-backdrop" role="dialog" aria-modal="true">
          <div className="dialog">
            <h2>Re-run {confirm.label}?</h2>
            <p>
              This will delete the cached output for <b>{confirm.label}</b> and
              every downstream stage, then re-run the pipeline. Any user-edited
              image prompts will be preserved.
            </p>
            <div className="actions">
              <button onClick={() => setConfirm(null)}>Cancel</button>
              <button className="primary"
                onClick={() => void trigger(confirm.stageName, true)}>
                Re-run
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}


function FilterAbstractionPicker({
  song, onCancel, onConfirmed,
}: {
  song: SongDetail;
  onCancel: () => void;
  onConfirmed: (filter: string, abstraction: number) => void;
}) {
  const [filter, setFilter] = useState(song.filter ?? "papercut");
  const [abstraction, setAbstraction] = useState(song.abstraction ?? 25);
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <div className="dialog">
        <h2>Pick filter and abstraction</h2>
        <p>
          Both are required for the world description stage. They flow through
          every downstream stage (storyboard, image prompts, keyframes).
          You can change them later via the top bar.
        </p>
        <div style={{ display: "grid", gap: 8 }}>
          <label>
            Filter:{" "}
            <input value={filter} onChange={e => setFilter(e.target.value)} />
          </label>
          <label>
            Abstraction (0-100):{" "}
            <input type="number" min={0} max={100} step={25}
              value={abstraction}
              onChange={e => setAbstraction(Math.max(0, Math.min(100, Number(e.target.value))))}
            />
          </label>
        </div>
        <div className="actions">
          <button onClick={onCancel}>Cancel</button>
          <button className="primary" onClick={() => onConfirmed(filter, abstraction)}>
            Confirm and run
          </button>
        </div>
      </div>
    </div>
  );
}

function RunAllOutstanding({ slug }: { slug: string }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<null | { triggered: Array<{ stage: string; run_id: number }>; blocked_at: { stage: string; reason: string } | null }>(null);
  const [error, setError] = useState<string | null>(null);

  const onClick = useCallback(async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await fetch(
        `/api/songs/${encodeURIComponent(slug)}/run-all-stages`,
        { method: "POST" },
      );
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(`${r.status} ${JSON.stringify(body)}`);
      }
      setResult(await r.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [slug]);

  return (
    <div className="run-all">
      <button onClick={onClick} disabled={busy}>
        {busy ? "Running…" : "▶▶ Run all outstanding"}
      </button>
      {error ? <span style={{ color: "#e06060", marginLeft: 8 }}>{error}</span> : null}
      {result ? (
        <span style={{ marginLeft: 8, color: "var(--text-dim)" }}>
          Queued {result.triggered.length} stage{result.triggered.length === 1 ? "" : "s"}
          {result.blocked_at
            ? `; blocked at ${result.blocked_at.stage}: ${result.blocked_at.reason}`
            : ""}
        </span>
      ) : null}
    </div>
  );
}

function RenderFinalAction({ song, status }: { song: SongDetail; status: StageStatus }) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [finished, setFinished] = useState<Array<{ file_path: string; created_at: number; quality_mode: string; scene_count: number }>>([]);
  const readyToRender = status.keyframes_done === status.keyframes_total && status.keyframes_total > 0;

  const loadFinished = useCallback(async () => {
    try {
      const r = await fetch(`/api/songs/${encodeURIComponent(song.slug)}/finished`);
      if (r.ok) {
        const data = await r.json();
        setFinished(data.finished ?? []);
      }
    } catch { /* non-fatal */ }
  }, [song.slug]);

  // Refresh finished list on mount.
  useState(() => { void loadFinished(); return 0; });

  const run = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(
        `/api/songs/${encodeURIComponent(song.slug)}/render-final`,
        { method: "POST" },
      );
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(`${r.status} ${JSON.stringify(body)}`);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      setConfirm(false);
      await loadFinished();
    }
  }, [song.slug, loadFinished]);

  return (
    <div className="render-final">
      <button
        className="primary"
        disabled={!readyToRender || busy}
        onClick={() => setConfirm(true)}
        title={readyToRender ? "Render final video" : "All keyframes must exist first"}
      >
        {busy ? "Rendering…" : "Render final video"}
      </button>
      {error ? <span style={{ color: "#e06060", marginLeft: 8 }}>{error}</span> : null}

      {finished.length > 0 ? (
        <div className="finished-list">
          <b>Finished videos:</b>
          <ul>
            {finished.map((f, i) => (
              <li key={i}>
                <a href={`/assets/outputs/${f.file_path.split("/outputs/")[1] ?? f.file_path}`} target="_blank" rel="noreferrer">
                  {f.quality_mode} · {f.scene_count} scenes · {new Date(f.created_at * 1000).toLocaleString()}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {confirm ? (
        <div className="dialog-backdrop" role="dialog" aria-modal="true">
          <div className="dialog">
            <h2>Render final video?</h2>
            <p>
              Renders any missing or stale clips at <b>{song.quality_mode}</b> mode,
              then stitches with the original audio into a single mp4.
              {song.quality_mode === "final"
                ? " ~110s per clip at 1080p/30fps."
                : " ~35s per clip at 512p/24fps."}
            </p>
            <div className="actions">
              <button onClick={() => setConfirm(false)}>Cancel</button>
              <button className="primary" onClick={run}>Render</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
