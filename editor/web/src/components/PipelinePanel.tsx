// Pipeline panel: horizontal breadcrumb of stages with traffic-light status.
// Story 9 introduced the per-stage trigger mechanism; story 17 replaces the
// row-of-pills layout with a breadcrumb and adds prereq-gating + a uniform
// regen-confirmation modal. Story 12 added transcribe progress + retry; that
// behaviour is preserved inside the new StageSegment.
import { useCallback, useEffect, useState } from "react";
import type { SongDetail, StageStatus } from "../types";
import type { RegenRunSummary } from "../api";
import { audioTranscribe, ApiError, patchSong } from "../api";

// Story 14: phase strings emitted by the audio-transcribe orchestrator.
const PHASE_LABEL: Record<string, string> = {
  "separating-vocals": "Separating vocals…",
  "transcribing":      "Transcribing…",
  "aligning":          "Aligning timings…",
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

type StageKey =
  | "transcription" | "world_brief" | "storyboard"
  | "image_prompts" | "keyframes" | "final_video";

type StageScope =
  | "stage_transcribe" | "stage_audio_transcribe" | "stage_world_brief"
  | "stage_storyboard" | "stage_image_prompts" | "stage_keyframes"
  | "final_video";

type StageDef = {
  key: StageKey;
  label: string;
  stageName: string;
  scope: StageScope;
  historyModel: "replace" | "take";
};

type SegmentStatus = "done" | "running" | "failed" | "pending" | "blocked";

const STAGES: readonly StageDef[] = [
  { key: "transcription",  label: "lyric alignment",   stageName: "transcribe",    scope: "stage_transcribe",         historyModel: "replace" },
  { key: "world_brief",    label: "world description", stageName: "world-brief",   scope: "stage_world_brief",       historyModel: "replace" },
  { key: "storyboard",     label: "storyboard",        stageName: "storyboard",    scope: "stage_storyboard",         historyModel: "replace" },
  { key: "image_prompts",  label: "image prompts",     stageName: "image-prompts", scope: "stage_image_prompts",      historyModel: "replace" },
  { key: "keyframes",      label: "keyframes",         stageName: "keyframes",     scope: "stage_keyframes",          historyModel: "take" },
  { key: "final_video",    label: "final video",       stageName: "render-final",  scope: "final_video",              historyModel: "replace" },
] as const;

// Each stage runs only after its prereqs are done. Linear chain today; the
// map gives the breadcrumb its prereq-blocked tooltip text.
const STAGE_PREREQS: Record<StageKey, StageKey[]> = {
  transcription: [],
  world_brief:   ["transcription"],
  storyboard:    ["world_brief"],
  image_prompts: ["storyboard"],
  keyframes:     ["image_prompts"],
  final_video:   ["keyframes"],
};

type StageDoneState = "done" | "progress" | "empty" | "error";

function deriveDoneState(
  stage: StageDef, song: SongDetail, status: StageStatus, finishedCount: number,
): { doneState: StageDoneState; summary: string } {
  if (stage.key === "keyframes") {
    const done = status.keyframes_done;
    const total = status.keyframes_total;
    return {
      doneState: done === total && total > 0 ? "done" : done > 0 ? "progress" : "empty",
      summary: ` (${done}/${total})`,
    };
  }
  if (stage.key === "image_prompts") {
    const total = song.scenes.length;
    const withPrompt = song.scenes.filter(s => s.image_prompt).length;
    return {
      doneState: withPrompt === total && total > 0 ? "done" : withPrompt > 0 ? "progress" : "empty",
      summary: ` (${withPrompt}/${total})`,
    };
  }
  if (stage.key === "final_video") {
    return {
      doneState: finishedCount > 0 ? "done" : "empty",
      summary: "",
    };
  }
  return {
    doneState: stage.key === "transcription"
      ? status.transcription
      : stage.key === "world_brief"
        ? status.world_brief
        : stage.key === "storyboard"
          ? status.storyboard
          : "empty",
    summary: "",
  };
}

function deriveSegmentStatus(args: {
  stage: StageDef;
  doneState: StageDoneState;
  activeRun: RegenRunSummary | undefined;
  failedRun: RegenRunSummary | undefined;
  prereqsDone: boolean;
}): SegmentStatus {
  const { doneState, activeRun, failedRun, prereqsDone } = args;
  if (activeRun) return "running";
  if (failedRun) return "failed";
  if (doneState === "error") return "failed";
  if (doneState === "done") return "done";
  if (doneState === "progress") return prereqsDone ? "pending" : "blocked";
  return prereqsDone ? "pending" : "blocked";
}

const STATUS_LABEL_BACKUP: Record<SegmentStatus, string> = {
  done: "done", running: "running", failed: "failed",
  pending: "ready", blocked: "blocked",
};

const STATUS_GLYPH: Record<SegmentStatus, string> = {
  done: "✓", running: "●", failed: "✕", pending: "○", blocked: "⌧",
};

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
  const [filterPicker, setFilterPicker] = useState<null | { pendingStageName: string; isRedo: boolean }>(null);
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
      setError(String(e));
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

  const segmentStatuses: Record<StageKey, SegmentStatus> = STAGES.reduce((acc, stage) => {
    const { doneState } = deriveDoneState(stage, song, status, finished.length);
    // Story 14: the transcription segment matches BOTH transcribe scopes so a
    // running stage_audio_transcribe run flips it to amber the same as
    // stage_transcribe.
    const matchesScope = (r: RegenRunSummary) =>
      stage.key === "transcription"
        ? (r.scope === "stage_transcribe" || r.scope === "stage_audio_transcribe")
        : r.scope === stage.scope;
    const stageRuns = (regenRuns ?? []).filter(matchesScope);
    const activeRun = stageRuns.find(r => r.status === "pending" || r.status === "running");
    const latestTerm = stageRuns.find(r => r.status === "done" || r.status === "failed" || r.status === "cancelled");
    const failedRun =
      stage.key === "transcription"
        ? (transcribeFailed ? latestTranscribe : undefined)
        : (latestTerm?.status === "failed" ? latestTerm : undefined);
    const prereqsDone = STAGE_PREREQS[stage.key].every(
      pk => acc[pk] === "done",
    );
    acc[stage.key] = deriveSegmentStatus({
      stage, doneState, activeRun, failedRun, prereqsDone,
    });
    return acc;
  }, {} as Record<StageKey, SegmentStatus>);

  const onSegmentClick = useCallback((stage: StageDef) => {
    const segStatus = segmentStatuses[stage.key];

    if (segStatus === "running") return;

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
      // World-brief on first run still needs filter/abstraction picked.
      if (stage.stageName === "world-brief"
          && (song.filter == null || song.abstraction == null)) {
        setFilterPicker({ pendingStageName: stage.stageName, isRedo: false });
        return;
      }
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
  }, [segmentStatuses, latestTranscribe, song.filter, song.abstraction, trigger]);

  return (
    <div className="pipeline-panel" aria-label="Pipeline stages">
      <div className="pipeline-breadcrumb">
        {STAGES.map((stage, i) => {
          const segStatus = segmentStatuses[stage.key];
          const { summary } = deriveDoneState(stage, song, status, finished.length);
          const isTranscribeRunning = stage.key === "transcription" && segStatus === "running";
          const isTranscribeFailed = stage.key === "transcription" && segStatus === "failed";
          // .pipeline-stage class kept for back-compat with story-9 tests; the
          // doneState class (.done / .progress / .empty) is also kept so older
          // assertions don't regress. The new stage-indicator is the visual
          // truth for traffic-light status.
          const { doneState } = deriveDoneState(stage, song, status, finished.length);
          const tooltipPrereqs = STAGE_PREREQS[stage.key]
            .filter(pk => segmentStatuses[pk] !== "done")
            .map(pk => STAGES.find(s => s.key === pk)?.label ?? pk);
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
                  ? `Complete ${tooltipPrereqs.join(", ")} first`
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
                {segStatus === "running" && stage.key === "transcription" ? (
                  // Story 14: phase-aware label for stage_audio_transcribe;
                  // null/unknown phase falls back to Story 12's ETA label.
                  activeTranscribe?.phase && PHASE_LABEL[activeTranscribe.phase] ? (
                    <span className="stage-running-detail transcribe-phase">
                      {PHASE_LABEL[activeTranscribe.phase]}
                    </span>
                  ) : (
                    <span className="stage-running-detail transcribe-eta">
                      Aligning lyrics — about {transcribeEtaSeconds(song, activeTranscribe)} seconds left
                    </span>
                  )
                ) : segStatus === "running" ? (
                  <span className="stage-running-detail">running…</span>
                ) : null}
                <span className="stage-status-label" aria-hidden="true">
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
                  Complete {tooltipPrereqs.join(", ")} first.
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
          onCancel={() => setFilterPicker(null)}
          onConfirmed={async (filter, abstraction) => {
            try {
              await fetch(
                `/api/songs/${encodeURIComponent(song.slug)}`,
                {
                  method: "PATCH",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ filter, abstraction }),
                },
              );
            } catch { /* non-fatal */ }
            const pendingStage = filterPicker.pendingStageName;
            const pendingRedo = filterPicker.isRedo;
            setFilterPicker(null);
            void trigger(pendingStage, pendingRedo);
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
