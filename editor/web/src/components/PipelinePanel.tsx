// Pipeline panel: horizontal breadcrumb of stages with traffic-light status.
// Story 9 introduced the per-stage trigger mechanism; story 17 replaces the
// row-of-pills layout with a breadcrumb and adds prereq-gating + a uniform
// regen-confirmation modal. Story 12 added transcribe progress + retry; that
// behaviour is preserved inside the new StageSegment.
import { useCallback, useEffect, useState } from "react";
import type { SongDetail, StageStatus } from "../types";
import type { RegenRunSummary } from "../api";
import {
  audioTranscribe,
  ApiError,
  formatApiError,
  getSong,
  isSavedConfigurationPreflightError,
  patchSong,
} from "../api";
import {
  ABSTRACTION_OPTIONS,
  FILTER_OPTIONS,
  describeAbstraction,
} from "../lib/filterOptions";
import {
  STAGES,
  deriveSongWorkflowState,
  type SegmentStatus,
  type StageDef,
  type StageKey,
  type StageScope,
} from "../lib/songWorkflowState";

// Story 14: phase strings emitted by the audio-transcribe orchestrator.
const PHASE_LABEL: Record<string, string> = {
  "separating-vocals": "Separating vocals",
  "transcribing":      "Transcribing",
  "aligning":          "Aligning timings",
};

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

function formatClock(totalSeconds: number): string {
  const safe = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function audioProgressDetail(song: SongDetail, activeRun: RegenRunSummary): string {
  const phase = activeRun.phase ?? "preparing";
  const phaseLabel = PHASE_LABEL[phase] ?? "Preparing";
  if (activeRun.scope !== "stage_audio_transcribe") {
    return `Aligning lyrics · about ${transcribeEtaSeconds(song, activeRun)} seconds left`;
  }

  if (phase === "transcribing" && activeRun.progress_pct != null && song.duration_s) {
    const pct = Math.max(0, Math.min(100, activeRun.progress_pct));
    const processed = (pct / PCT_TO_FRACTION) * song.duration_s;
    return `${phaseLabel} · ${formatClock(processed)} / ${formatClock(song.duration_s)} processed`;
  }

  if (activeRun.started_at != null) {
    const elapsed = Math.max(0, Date.now() / 1000 - activeRun.started_at);
    return `${phaseLabel} · ${formatClock(elapsed)} elapsed`;
  }

  return phaseLabel;
}

function workflowProgressDetail(
  progress: { operation: string; processed_seconds: number | null; total_seconds: number | null; progress_pct: number | null; detail: string | null } | null,
): string | null {
  if (!progress) return null;
  if (progress.processed_seconds != null && progress.total_seconds != null) {
    return `${progress.operation} · ${formatClock(progress.processed_seconds)} / ${formatClock(progress.total_seconds)} processed`;
  }
  if (progress.progress_pct != null) {
    return `${progress.operation} · ${progress.progress_pct}%`;
  }
  return progress.operation;
}

const STATUS_LABEL_BACKUP: Record<SegmentStatus, string> = {
  done: "done", running: "running", failed: "failed",
  pending: "ready", blocked: "blocked",
};

const STATUS_GLYPH: Record<SegmentStatus, string> = {
  done: "✓", running: "●", failed: "⟳", pending: "○", blocked: "⌧",
};

async function runStage(slug: string, stageName: string, redo: boolean) {
  const r = await fetch(
    `/api/songs/${encodeURIComponent(slug)}/stages/${stageName}?redo=${redo}`,
    { method: "POST" },
  );
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new ApiError(r.status, body, `${stageName} failed`);
  }
  return r.json();
}

type FinishedVideo = {
  file_path: string; created_at: number; quality_mode: string; scene_count: number;
};

export default function PipelinePanel({
  song, status, regenRuns, onSongUpdate,
}: {
  song: SongDetail;
  status: StageStatus;
  regenRuns?: RegenRunSummary[];
  onSongUpdate?: (s: SongDetail) => void;
}) {
  // Story 14 generalises the transcribe-row state-tracking to cover BOTH
  // stage_transcribe (existing forced-alignment path) and stage_audio_transcribe
  // (new audio-transcribe path) so the lyric-alignment segment shows a unified
  // running/failed state regardless of which path the user picked.
  const transcribeRuns = (regenRuns ?? []).filter(
    r => r.scope === "stage_transcribe" || r.scope === "stage_audio_transcribe",
  );
  const activeTranscribe = transcribeRuns.find(
    r => r.status === "pending" || r.status === "running",
  );
  const latestTranscribe = transcribeRuns.find(
    r => r.status === "done" || r.status === "failed" || r.status === "cancelled",
  );
  const [dismissedFailedId, setDismissedFailedId] = useState<number | null>(null);
  const transcribeFailed =
    !activeTranscribe
    && latestTranscribe?.status === "failed"
    && latestTranscribe.id !== dismissedFailedId;

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filterPicker, setFilterPicker] = useState<null | { mode: "setup" | "change" }>(null);
  const [worldBriefModal, setWorldBriefModal] = useState(false);
  const [pendingRegen, setPendingRegen] = useState<null | { scope: StageScope; label: string; stageName: string }>(null);
  const [tooltipKey, setTooltipKey] = useState<StageKey | null>(null);
  // Story 14: audio-transcribe modal state. Lives at panel scope so the
  // confirm + overwrite branches share state.
  const [pendingAudioTranscribe, setPendingAudioTranscribe] = useState(false);

  // Lifted from RenderFinalAction so the breadcrumb's final-video segment can
  // derive its done-state from finished.length.
  const [finished, setFinished] = useState<FinishedVideo[]>([]);
  const [renderConfirm, setRenderConfirm] = useState(false);
  const [renderBusy, setRenderBusy] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);

  const loadFinished = useCallback(async () => {
    try {
      const r = await fetch(`/api/songs/${encodeURIComponent(song.slug)}/finished`);
      if (r.ok) {
        const data = await r.json();
        setFinished(data.finished ?? []);
      }
    } catch { /* non-fatal */ }
  }, [song.slug]);
  useEffect(() => { void loadFinished(); }, [loadFinished]);

  const trigger = useCallback(async (stageName: string, isRedo: boolean) => {
    setBusy(stageName);
    setError(null);
    try {
      await runStage(song.slug, stageName, isRedo);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(null);
    }
  }, [song.slug]);

  const runRenderFinal = useCallback(async () => {
    setRenderBusy(true);
    setRenderError(null);
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
      setRenderError(String(e));
    } finally {
      setRenderBusy(false);
      setRenderConfirm(false);
      await loadFinished();
    }
  }, [song.slug, loadFinished]);

  const workflow = deriveSongWorkflowState({
    song,
    status,
    regenRuns,
    finishedCount: finished.length,
    dismissedFailedTranscribeId: dismissedFailedId,
  });

  const onSegmentClick = useCallback((stage: StageDef) => {
    const stageState = workflow[stage.key];
    const segStatus = stageState.status;
    const visualLanguageMissing = stage.key === "world_brief"
      && (song.filter == null || song.abstraction == null);
    const blockedForVisualLanguage = visualLanguageMissing
      && stageState.blockedReason === "Choose a filter and abstraction first.";

    if (segStatus === "running") return;

    if ((segStatus === "blocked" && blockedForVisualLanguage)
        || (segStatus === "pending" && visualLanguageMissing)) {
      setFilterPicker({ mode: "setup" });
      return;
    }

    if (segStatus === "blocked") {
      setTooltipKey(prev => (prev === stage.key ? null : stage.key));
      return;
    }

    if (segStatus === "failed") {
      // Null-state retry — no committed output to replace, no confirmation.
      if (stage.key === "transcription" && latestTranscribe) {
        setDismissedFailedId(latestTranscribe.id);
      }
      void trigger(stage.stageName, true);
      return;
    }

    if (segStatus === "pending") {
      if (stage.key === "final_video") {
        setRenderConfirm(true);
        return;
      }
      void trigger(stage.stageName, false);
      return;
    }

    // segStatus === "done"
    if (stage.key === "world_brief") {
      // World-brief has its own edit-or-regen modal (which itself confirms
      // before regenerating). Story 17 leaves that flow intact.
      setWorldBriefModal(true);
      return;
    }
    if (stage.key === "final_video") {
      // Final-video has its own render-confirm modal.
      setRenderConfirm(true);
      return;
    }
    setPendingRegen({ scope: stage.scope, label: stage.label, stageName: stage.stageName });
  }, [workflow, latestTranscribe, song.filter, song.abstraction, trigger]);

  return (
    <div className="pipeline-panel" aria-label="Pipeline stages">
      <div className="pipeline-breadcrumb">
        {STAGES.map((stage, i) => {
          const stageState = workflow[stage.key];
          const segStatus = stageState.status;
          const { summary } = stageState;
          const isTranscribeRunning = stage.key === "transcription" && segStatus === "running";
          const isTranscribeFailed = stage.key === "transcription" && segStatus === "failed";
          const isStageFailed = stage.key !== "transcription" && segStatus === "failed";
          const progressText = workflowProgressDetail(stageState.progress);
          // .pipeline-stage class kept for back-compat with story-9 tests; the
          // doneState class (.done / .progress / .empty) is also kept so older
          // assertions don't regress. The new stage-indicator is the visual
          // truth for traffic-light status.
          const { doneState, tooltipPrereqs } = stageState;
          return (
            <div key={stage.key}
              className={`pipeline-stage ${doneState} ${segStatus}`}
              data-stage={stage.key}
              data-status={segStatus}
            >
              <button
                type="button"
                className={`stage-segment-btn`}
                onClick={() => onSegmentClick(stage)}
                disabled={busy === stage.stageName || segStatus === "running" || (stage.key === "transcription" && song.scenes.length === 0)}
                title={stage.key === "transcription" && song.scenes.length === 0
                  ? "Transcribe from audio first"
                  : segStatus === "blocked"
                  ? (stageState.blockedReason ?? `Complete ${tooltipPrereqs.join(", ")} first`)
                  : stageState.actionState === "stale" ? `Regenerate stale ${stage.label}`
                  : segStatus === "done" ? `Regenerate ${stage.label}`
                  : segStatus === "failed" ? `Retry ${stage.label}`
                  : `Run ${stage.label}`}
              >
                <span className={`stage-indicator stage-indicator--${segStatus}`}
                  aria-label={STATUS_LABEL_BACKUP[segStatus]}
                >
                  <span className="stage-indicator-glyph" aria-hidden="true">
                    {STATUS_GLYPH[segStatus]}
                  </span>
                </span>
                <span className="label">
                  {stage.label}{summary}
                </span>
                {segStatus === "running" && progressText ? (
                  <span className="stage-running-detail">
                    {progressText}
                  </span>
                ) : segStatus === "running" && stage.key === "transcription" && activeTranscribe ? (
                  <span className="stage-running-detail transcribe-phase">
                    {audioProgressDetail(song, activeTranscribe)}
                  </span>
                ) : segStatus === "running" ? (
                  <span className="stage-running-detail">running…</span>
                ) : stageState.actionState === "stale" && stageState.staleReasons.length ? (
                  <span className="stage-running-detail">{stageState.staleReasons[0]}</span>
                ) : null}
                <span className="stage-status-label sr-only">
                  {STATUS_LABEL_BACKUP[segStatus]}
                </span>
              </button>
              {/* Story 14: when the lyric-alignment segment is pending and
                  no scenes exist yet, expose the audio-transcribe alternative
                  alongside the existing forced-alignment trigger. */}
              {stage.key === "transcription"
                && segStatus === "pending"
                && song.scenes.length === 0 ? (
                <button
                  type="button"
                  className="transcribe-from-audio-btn"
                  onClick={() => setPendingAudioTranscribe(true)}
                  title="Transcribe lyrics from the song's audio"
                >
                  Transcribe from audio
                </button>
              ) : null}
              {tooltipKey === stage.key && segStatus === "blocked" ? (
                <div className="pipeline-tooltip" role="tooltip">
                  {stageState.blockedReason ?? `Complete ${tooltipPrereqs.join(", ")} first.`}
                </div>
              ) : null}
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
                      // Story 14: retry the SAME scope as the failed run.
                      // stage_audio_transcribe must call audioTranscribe with
                      // force=true (a partial run may have written
                      // intermediates we want to overwrite).
                      if (latestTranscribe?.scope === "stage_audio_transcribe") {
                        void audioTranscribe(song.slug, { force: true });
                      } else {
                        void trigger("transcribe", true);
                      }
                    }}
                    disabled={busy === "transcribe"}
                  >
                    Try again
                  </button>
                </div>
              ) : null}
              {isStageFailed ? (
                <div className="stage-failed" role="alert">
                  <span>
                    {stageState.failedRun?.error ?? `${stage.label} failed. Try again.`}
                  </span>
                  <button
                    onClick={() => trigger(stage.stageName, true)}
                    disabled={busy === stage.stageName}
                  >
                    Try again
                  </button>
                </div>
              ) : null}
              {/* Suppress unused-warning */}
              {isTranscribeRunning ? null : null}
              {i < STAGES.length - 1 ? (
                <span className="pipeline-chevron" aria-hidden="true">›</span>
              ) : null}
            </div>
          );
        })}
      </div>

      {error ? <span className="pipeline-error" style={{ color: "#e06060" }}>{error}</span> : null}
      {renderError ? <span className="pipeline-error" style={{ color: "#e06060" }}>{renderError}</span> : null}

      <RunAllOutstanding slug={song.slug} />

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

      {filterPicker ? (
        <FilterAbstractionPicker
          song={song}
          mode={filterPicker.mode}
          onCancel={() => setFilterPicker(null)}
          onConfirmed={async (filter, abstraction) => {
            try {
              setError(null);
              const updated = await patchSong(song.slug, { filter, abstraction });
              onSongUpdate?.(updated);
              setFilterPicker(null);
            } catch (e) {
              if (isSavedConfigurationPreflightError(e)) {
                const updated = await getSong(song.slug);
                onSongUpdate?.(updated);
                setFilterPicker(null);
              }
              setError(formatApiError(e));
            }
          }}
        />
      ) : null}

      {pendingRegen ? (
        <RegenConfirmationModal
          historyModel={STAGES.find(s => s.scope === pendingRegen.scope)?.historyModel ?? "replace"}
          label={pendingRegen.label}
          onCancel={() => setPendingRegen(null)}
          onConfirm={() => {
            const target = pendingRegen;
            setPendingRegen(null);
            void trigger(target.stageName, true);
          }}
        />
      ) : null}

      {pendingAudioTranscribe ? (
        <ConfirmAudioTranscribeModal
          slug={song.slug}
          onClose={() => setPendingAudioTranscribe(false)}
        />
      ) : null}

      {worldBriefModal ? (
        <WorldBriefModal
          song={song}
          onClose={() => setWorldBriefModal(false)}
          onSaved={s => onSongUpdate?.(s)}
          onChangeVisualLanguage={() => {
            setWorldBriefModal(false);
            setFilterPicker({ mode: "change" });
          }}
          onRegenConfirmed={async () => {
            setWorldBriefModal(false);
            await trigger("world-brief", true);
          }}
        />
      ) : null}

      {renderConfirm ? (
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
              <button onClick={() => setRenderConfirm(false)}>Cancel</button>
              <button className="primary" onClick={runRenderFinal} disabled={renderBusy}>
                {renderBusy ? "Rendering…" : "Render"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ConfirmAudioTranscribeModal({
  slug, onClose,
}: {
  slug: string;
  onClose: () => void;
}) {
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const start = useCallback(async (force: boolean) => {
    setBusy(true);
    setErrMsg(null);
    try {
      await audioTranscribe(slug, { force });
      onClose();
    } catch (e) {
      // Detect the overwrite_required path so the modal can flip to the
      // overwrite-confirm copy without bouncing back to the empty state.
      // FastAPI wraps HTTPException(detail=X) as `{detail: X}` in the body
      // so the code lives at e.detail.detail.code; some test paths inline
      // the payload at e.detail.code, so probe both.
      const probe = (e instanceof ApiError && e.detail) as { detail?: { code?: string }; code?: string } | false;
      const code = probe ? (probe.detail?.code ?? probe.code) : undefined;
      if (e instanceof ApiError && e.status === 409 && code === "overwrite_required") {
        setOverwrite(true);
      } else {
        setErrMsg(String(e));
      }
    } finally {
      setBusy(false);
    }
  }, [slug, onClose]);

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <div className="dialog">
        <h2>Transcribe from audio</h2>
        <div className="body">
          {overwrite ? (
            <p>
              A lyrics file already exists for this song. Transcribing again
              will overwrite it.
            </p>
          ) : (
            <p>
              Transcribing from audio separates the vocals from the music
              and runs speech-to-text. Takes several minutes; first run
              downloads several gigabytes of model files to your machine.
            </p>
          )}
          {errMsg ? (
            <p style={{ color: "#e06060", fontSize: 12 }}>{errMsg}</p>
          ) : null}
        </div>
        <div className="actions">
          <button onClick={onClose} disabled={busy}>Cancel</button>
          <button
            className="primary"
            onClick={() => start(overwrite)}
            disabled={busy}
          >
            {busy ? "Starting…" : overwrite ? "Overwrite" : "Start"}
          </button>
        </div>
      </div>
    </div>
  );
}


function RegenConfirmationModal({
  historyModel, label, onCancel, onConfirm,
}: {
  historyModel: "replace" | "take";
  label: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const body = historyModel === "take"
    ? `Regenerating creates a new take alongside the existing one. The current selection stays unchanged.`
    : `Regenerating will replace the existing ${label}.`;
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <div className="dialog">
        <h2>Regenerate {label}?</h2>
        <div className="body">
          <p>{body}</p>
        </div>
        <div className="actions">
          <button onClick={onCancel}>Cancel</button>
          <button className="primary" onClick={onConfirm}>Regenerate</button>
        </div>
      </div>
    </div>
  );
}

function WorldBriefModal({
  song, onClose, onSaved, onChangeVisualLanguage, onRegenConfirmed,
}: {
  song: SongDetail;
  onClose: () => void;
  onSaved: (s: SongDetail) => void;
  onChangeVisualLanguage: () => void;
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
          <button onClick={onChangeVisualLanguage}>
            Change visual language
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
  song, mode, onCancel, onConfirmed,
}: {
  song: SongDetail;
  mode: "setup" | "change";
  onCancel: () => void;
  onConfirmed: (filter: string, abstraction: number) => Promise<void> | void;
}) {
  const [filter, setFilter] = useState(song.filter ?? FILTER_OPTIONS[0]!.name);
  const [abstraction, setAbstraction] = useState(song.abstraction ?? 0);
  const [saving, setSaving] = useState(false);
  const selectedAbstraction = describeAbstraction(abstraction);
  const isChange = mode === "change";
  const unchanged = filter === song.filter && abstraction === song.abstraction;
  const submit = useCallback(async () => {
    setSaving(true);
    try {
      await onConfirmed(filter, abstraction);
    } finally {
      setSaving(false);
    }
  }, [filter, abstraction, onConfirmed]);
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <div className="dialog">
        <h2>{isChange ? "Change the visual language" : "Choose the visual language"}</h2>
        <p>
          {isChange
            ? "Changing visual language regenerates the world description, storyboard, scene prompts, and keyframes. Existing clip takes are preserved but may be marked stale."
            : "Pick the material style for the whole video and how literal the generated imagery should be. These choices shape the world description, storyboard, scene prompts, and keyframes."}
        </p>
        <div className="setup-picker">
          <label>
            Filter
            <select value={filter} onChange={e => setFilter(e.target.value)}>
              {FILTER_OPTIONS.map(option => (
                <option key={option.name} value={option.name}>
                  {option.name} - {option.description}
                </option>
              ))}
            </select>
          </label>
          <div className="filter-description-list" aria-label="Filter descriptions">
            {FILTER_OPTIONS.map(option => (
              <button
                key={option.name}
                type="button"
                className={option.name === filter ? "selected" : ""}
                onClick={() => setFilter(option.name)}
              >
                <b>{option.name}</b>
                <span>{option.description}</span>
              </button>
            ))}
          </div>
          <label>
            Abstraction
            <select
              value={abstraction}
              onChange={e => setAbstraction(Number(e.target.value))}
            >
              {ABSTRACTION_OPTIONS.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          {selectedAbstraction ? (
            <p className="abstraction-help">{selectedAbstraction.description}</p>
          ) : null}
        </div>
        <div className="actions">
          <button onClick={onCancel} disabled={saving}>Cancel</button>
          <button className="primary" onClick={submit} disabled={saving || (isChange && unchanged)}>
            {saving ? "Saving…" : isChange ? "Apply and regenerate" : "Confirm and run"}
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
