// Story 9 — pipeline stage buttons. Each button POSTs to
// /api/songs/:slug/stages/:stage which enqueues a real gen_keyframes.py
// subprocess (or the fake under tests). The user sees DB-derived progress
// on the next SWR revalidation.
import { useCallback, useState } from "react";
import type { SongDetail, StageStatus } from "../types";
import type { RegenRunSummary } from "../api";
import { patchSong } from "../api";

// ETA for forced alignment. Two sources:
// (1) Live: regen_runs.progress_pct + started_at (set by the [align] N%
//     event from whisperx_align). remaining = (elapsed/pct)*100 - elapsed.
// (2) Heuristic fallback: 0.5 * song.duration_s, used until the first
//     progress event lands.
// Both rounded to nearest 5s, ≥5s.
const ETA_FALLBACK_RATIO = 0.5;
const ETA_DEFAULT_DURATION_S = 60;
const ETA_ROUND_TO_S = 5;
const PCT_TO_FRACTION = 100;

function roundToFiveSeconds(n: number): number {
  return Math.max(ETA_ROUND_TO_S, Math.round(n / ETA_ROUND_TO_S) * ETA_ROUND_TO_S);
}

function transcribeEtaSeconds(
  song: SongDetail,
  activeRun?: { progress_pct: number | null; started_at: number | null } | null,
  nowS: number = Date.now() / 1000,
): number {
  if (activeRun?.progress_pct != null && activeRun.progress_pct > 0
      && activeRun.started_at != null) {
    const elapsed = Math.max(0, nowS - activeRun.started_at);
    const totalEstimated = (elapsed / activeRun.progress_pct) * PCT_TO_FRACTION;
    const remaining = Math.max(0, totalEstimated - elapsed);
    return roundToFiveSeconds(remaining);
  }
  const dur = song.duration_s ?? ETA_DEFAULT_DURATION_S;
  return roundToFiveSeconds(ETA_FALLBACK_RATIO * dur);
}

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

export default function PipelinePanel({
  song, status, regenRuns, onSongUpdate,
}: {
  song: SongDetail;
  status: StageStatus;
  regenRuns?: RegenRunSummary[];
  onSongUpdate?: (s: SongDetail) => void;
}) {
  const transcribeRuns = (regenRuns ?? []).filter(r => r.scope === "stage_transcribe");
  const activeTranscribe = transcribeRuns.find(
    r => r.status === "pending" || r.status === "running",
  );
  // Most recent terminal transcribe run (sorted desc by created_at on the
  // backend already; take first non-active).
  const latestTranscribe = transcribeRuns.find(
    r => r.status === "done" || r.status === "failed" || r.status === "cancelled",
  );
  // Optimistic dismissal: when the user clicks Try again, we hide the
  // failed banner immediately (tracked by the failed run id) so they
  // don't see the old error linger until the next SWR poll surfaces the
  // freshly-pending run row.
  const [dismissedFailedId, setDismissedFailedId] = useState<number | null>(null);
  const transcribeFailed =
    !activeTranscribe
    && latestTranscribe?.status === "failed"
    && latestTranscribe.id !== dismissedFailedId;
  const [confirm, setConfirm] = useState<null | { stageName: string; isRedo: boolean; label: string }>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // PRD: 'filter and abstraction pickers appear as a one-time dialog the
  // first time the world description is generated'. If either is unset we
  // open the picker before dispatching the world-brief run.
  const [filterPicker, setFilterPicker] = useState<null | { pendingStageName: string; isRedo: boolean }>(null);
  // World-brief editing / regen modal: opens when a done world_brief row is
  // clicked. Edits go through PATCH /api/songs/:slug; regen kicks the usual
  // stage chain with redo=true.
  const [worldBriefModal, setWorldBriefModal] = useState(false);

  const onClick = useCallback((stageName: string, label: string, isRedo: boolean) => {
    const needsFilterPicker =
      stageName === "world-brief" && (song.filter == null || song.abstraction == null);
    if (needsFilterPicker) {
      setFilterPicker({ pendingStageName: stageName, isRedo });
      return;
    }
    // World-brief when already done opens the edit-or-regen modal rather
    // than the generic re-run confirmation.
    if (stageName === "world-brief" && isRedo && song.world_brief) {
      setWorldBriefModal(true);
      return;
    }
    if (isRedo) {
      setConfirm({ stageName, isRedo: true, label });
    } else {
      void trigger(stageName, false);
    }
  }, [song.filter, song.abstraction, song.world_brief]);

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
        // Transcribe row gets running / failed states from the regen-runs poll
        // so the user sees the background subprocess instead of an inert row.
        if (stage.key === "transcription" && activeTranscribe) state = "running";
        else if (stage.key === "transcription" && transcribeFailed) state = "failed";
        const isRedo = state === "done";
        const isTranscribeRunning = stage.key === "transcription" && state === "running";
        const isTranscribeFailed = stage.key === "transcription" && state === "failed";
        return (
          <div key={stage.key} className={`pipeline-stage ${state}`}>
            <span className="label">
              {stage.label}{summary}
              {isTranscribeRunning ? (
                <span
                  className="transcribe-eta"
                  style={{ marginLeft: 8, color: "var(--text-dim)", fontSize: 12 }}
                >
                  Aligning lyrics — about {transcribeEtaSeconds(song, activeTranscribe)} seconds left
                </span>
              ) : null}
            </span>
            <button
              onClick={() => onClick(stage.stageName, stage.label, isRedo)}
              disabled={busy === stage.stageName || isTranscribeRunning}
              title={isRedo
                ? `Re-run ${stage.label} (marks downstream stages stale)`
                : `Run ${stage.label}`}
            >
              {busy === stage.stageName || isTranscribeRunning
                ? "…"
                : (isRedo ? "↻" : "▶")}
            </button>
            {isTranscribeFailed ? (
              <div
                className="transcribe-failed"
                role="alert"
                style={{
                  flexBasis: "100%",
                  marginTop: 4,
                  padding: "6px 8px",
                  background: "rgba(224, 96, 96, 0.08)",
                  borderLeft: "3px solid #e06060",
                  color: "#e06060",
                  fontSize: 12,
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <span style={{ flex: 1 }}>
                  {latestTranscribe?.error ?? "Transcribe failed"}
                </span>
                <button
                  onClick={() => {
                    if (latestTranscribe) setDismissedFailedId(latestTranscribe.id);
                    void trigger("transcribe", true);
                  }}
                  disabled={busy === "transcribe"}
                >
                  Try again
                </button>
              </div>
            ) : null}
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

      {worldBriefModal ? (
        <WorldBriefModal
          song={song}
          onClose={() => setWorldBriefModal(false)}
          onSaved={s => onSongUpdate?.(s)}
          onRegenConfirmed={async () => {
            setWorldBriefModal(false);
            await trigger("world-brief", true);
          }}
        />
      ) : null}
    </div>
  );
}

function WorldBriefModal({
  song, onClose, onSaved, onRegenConfirmed,
}: {
  song: SongDetail;
  onClose: () => void;
  onSaved: (s: SongDetail) => void;
  onRegenConfirmed: () => Promise<void>;
}) {
  const [text, setText] = useState(song.world_brief ?? "");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmRegen, setConfirmRegen] = useState(false);

  const onSave = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await patchSong(song.slug, { world_brief: text });
      onSaved(updated);
      onClose();
    } catch (e) {
      setSaveError(String(e));
    } finally {
      setSaving(false);
    }
  }, [song.slug, text, onSaved, onClose]);

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <div className="dialog world-brief-dialog">
        <h2>World description for {song.slug}</h2>
        <p style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 0 }}>
          Edit the text and save, or regenerate the entire chain from scratch.
        </p>
        <textarea
          className="world-brief-textarea"
          value={text}
          onChange={e => setText(e.target.value)}
          spellCheck
        />
        {saveError ? (
          <p style={{ color: "#e06060", fontSize: 12 }}>{saveError}</p>
        ) : null}
        <div className="actions">
          <button onClick={onClose}>Cancel</button>
          <button onClick={onSave} disabled={saving || text === (song.world_brief ?? "")}>
            {saving ? "Saving…" : "Save edit"}
          </button>
          <button
            className="primary danger"
            onClick={() => setConfirmRegen(true)}
            title="Regenerate the world description and every downstream stage"
          >
            Regenerate
          </button>
        </div>

        {confirmRegen ? (
          <div className="dialog-backdrop" role="dialog" aria-modal="true">
            <div className="dialog">
              <h2>This is a big deal. It affects the entire project and everything will be rebuilt. OK?</h2>
              <p style={{ color: "var(--text-dim)" }}>
                Regenerating the world description invalidates every downstream
                stage — storyboard, image prompts, and all keyframes. Existing
                clip takes are preserved but marked stale.
              </p>
              <div className="actions">
                <button onClick={() => setConfirmRegen(false)}>Cancel</button>
                <button
                  className="primary danger"
                  onClick={() => { setConfirmRegen(false); void onRegenConfirmed(); }}
                >
                  Regenerate
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
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
