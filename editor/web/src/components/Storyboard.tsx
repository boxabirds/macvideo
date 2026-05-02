// Story 3 — storyboard LHS editor. Per-scene rows with inline-editable
// beat / subject / camera intent / prompt; blur triggers PATCH. Tracks
// per-field dirty + error state so users see pending saves and failures.
// Staleness chips reflect backend-driven dirty_flags including the
// identity-chain cascade on N+1..N+4 beat/camera/subject edits.
//
// Presentation layer additions (post-Story 3):
//   - Collapsible rows: header-only by default; expando toggles the body.
//   - target_text is corrected through selectable transcript word tokens.
//   - Status chips show icons: ● (done), ● amber (pending/stale), ↻ (in-flight), ⚠ (error).
import { memo, useCallback, useEffect, useRef, useState } from "react";
import type { Scene, SongDetail } from "../types";
import {
  ApiError,
  type SceneTake,
  type TranscriptResponse,
  applyTranscriptCorrection,
  listTakes,
  patchScene,
  redoTranscriptCorrection,
  regenerateScene,
  revertTranscriptCorrection,
  selectTake,
  undoTranscriptCorrection,
} from "../api";
import {
  type SceneArtefactKind,
  sceneGenerationGate,
} from "../lib/editorWorkflowState";
import { useSceneTranscript } from "../hooks/useSceneTranscript";

// Module-scoped retry queue. A queued retry is a field edit whose PATCH
// failed with a network error (fetch threw — not an API-level validation
// error). We replay the queue whenever the browser reports it's back
// online, and surface its presence through beforeunload so the browser
// warns on tab close with unsaved work pending.
type PendingRetry = {
  slug: string;
  sceneIndex: number;
  field: EditableField;
  value: string;
  onAck: (updated: Scene) => void;
  onGiveUp: (msg: string) => void;
};
const retryQueue: PendingRetry[] = [];

function isNetworkFailure(e: unknown): boolean {
  // fetch() throws a TypeError for offline / CORS / DNS failures.
  return e instanceof TypeError;
}

// How long a row stays "auto-scroll-followable" after a user scroll gesture.
// After this we resume auto-scrolling the current scene into view.
const SCROLL_OVERRIDE_MS = 3000;
const SUMMARY_WORDS = 5;
const noopSeekToTime = () => {};

type EditableField =
  | "beat"
  | "subject_focus"
  | "camera_intent"
  | "image_prompt";

type ActiveArtefacts = "keyframe" | "clip";
type ActiveRegensMap = Record<number, Set<ActiveArtefacts>>;

type ChipState = "done" | "pending" | "in_progress" | "error";

function StatusChip({ label, state }: { label: string; state: ChipState }) {
  // Visual language:
  //   done          — filled green dot
  //   pending/stale — filled amber dot (asset not yet fresh)
  //   in_progress   — spinning ↻
  //   error         — red ⚠
  let glyph: string;
  let title: string;
  switch (state) {
    case "done":
      glyph = "\u25CF"; // ●
      title = "up to date";
      break;
    case "in_progress":
      glyph = "\u21BB"; // ↻
      title = "regenerating…";
      break;
    case "error":
      glyph = "\u26A0"; // ⚠
      title = "missing asset — hover for detail";
      break;
    case "pending":
    default:
      glyph = "\u25CF"; // ●
      title = "stale / pending (regenerate to update)";
      break;
  }
  return (
    <span className={`chip ${label} ${state}`} title={title}>
      <span className={`chip-glyph ${state === "in_progress" ? "spin" : ""}`}>
        {glyph}
      </span>
      <span className="chip-label">{label}</span>
    </span>
  );
}

function chipStateFor(
  scene: Scene,
  kind: ActiveArtefacts,
  isActive: boolean,
): ChipState {
  if (isActive) return "in_progress";
  if (scene.missing_assets.includes(kind)) return "error";
  const selected = kind === "keyframe"
    ? scene.selected_keyframe_path
    : scene.selected_clip_path;
  const staleFlag = kind === "keyframe" ? "keyframe_stale" : "clip_stale";
  if (!selected) return "pending";
  if (scene.dirty_flags.includes(staleFlag)) return "pending";
  return "done";
}

function sceneSummary(text: string | null | undefined): string {
  const words = (text ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "(empty phrase)";
  return words.slice(0, SUMMARY_WORDS).join(" ");
}

type Props = {
  song: SongDetail;
  cameraIntents: string[];
  playingSceneIdx: number | null;
  onSeekToScene: (idx: number) => void;
  onSeekToTime?: (timeSeconds: number) => void;
  onPatch: (idx: number, updated: Scene) => void;
  // Optional map of scene_index → set of artefacts currently regenerating.
  // Drives the "in-progress" state on status chips. Absent during unit
  // tests; defaults to an empty map.
  activeRegens?: ActiveRegensMap;
};

const SceneRow = memo(function SceneRow({
  scene, cameraIntents, current, onSceneClick, onPatch, slug,
  activeArtefacts, expanded, onToggleExpanded, song, onSeekToTime,
}: {
  song: SongDetail;
  scene: Scene;
  cameraIntents: string[];
  current: boolean;
  onSceneClick: (sceneIndex: number) => void;
  onSeekToTime: (timeSeconds: number) => void;
  onPatch: (sceneIndex: number, updated: Scene) => void;
  slug: string;
  activeArtefacts: Set<ActiveArtefacts>;
  expanded: boolean;
  onToggleExpanded: (sceneIndex: number) => void;
}) {
  // Per-field buffers so typing in one field doesn't re-render the others.
  const [beat, setBeat] = useState(scene.beat ?? "");
  const [subject, setSubject] = useState(scene.subject_focus ?? "");
  const [prompt, setPrompt] = useState(scene.image_prompt ?? "");
  const [camera, setCamera] = useState(scene.camera_intent ?? "");
  const [selection, setSelection] = useState<null | { start: number; end: number }>(null);
  const [correctionModal, setCorrectionModal] = useState<null | { text: string; error: string | null; busy: boolean }>(null);
  const selectingRef = useRef(false);
  const selectionRef = useRef<null | { start: number; end: number }>(null);
  const {
    words: transcriptWords,
    targetText: transcriptTargetText,
    error: transcriptError,
    isLoading: transcriptLoading,
    setTranscriptResponse,
  } = useSceneTranscript(slug, scene.index, scene.target_text, expanded);

  // Per-field saving + error state. `saving` is the set of fields with an
  // in-flight PATCH; `errors` is { field -> message } when PATCH failed and
  // the buffer is being kept so the user can retry. Both are scoped to
  // this scene row.
  const [saving, setSaving] = useState<Set<EditableField>>(new Set());
  const [errors, setErrors] = useState<Partial<Record<EditableField, string>>>({});

  // Keep buffers in sync when the scene prop changes (e.g., on refetch), but
  // only for fields that aren't currently being edited (saving/errored).
  useEffect(() => { setBeat(scene.beat ?? ""); }, [scene.beat]);
  useEffect(() => { setSubject(scene.subject_focus ?? ""); }, [scene.subject_focus]);
  useEffect(() => { setPrompt(scene.image_prompt ?? ""); }, [scene.image_prompt]);
  useEffect(() => { setCamera(scene.camera_intent ?? ""); }, [scene.camera_intent]);
  const updateSelection = useCallback((next: null | { start: number; end: number }) => {
    selectionRef.current = next;
    setSelection(next);
  }, []);
  useEffect(() => {
    if (typeof transcriptTargetText !== "string" || transcriptTargetText === scene.target_text) return;
    onPatch(scene.index, { ...scene, target_text: transcriptTargetText });
  }, [onPatch, scene, scene.target_text, transcriptTargetText]);

  const kfState = chipStateFor(scene, "keyframe", activeArtefacts.has("keyframe"));
  const clipState = chipStateFor(scene, "clip", activeArtefacts.has("clip"));

  const currentBuffers: Record<EditableField, string> = {
    beat,
    subject_focus: subject,
    camera_intent: camera,
    image_prompt: prompt,
  };
  const savedValues: Record<EditableField, string> = {
    beat: scene.beat ?? "",
    subject_focus: scene.subject_focus ?? "",
    camera_intent: scene.camera_intent ?? "",
    image_prompt: scene.image_prompt ?? "",
  };
  const isDirty = (f: EditableField) => currentBuffers[f] !== savedValues[f];

  const commit = useCallback(async (field: EditableField, newValue: string) => {
    if (savedValues[field] === newValue) return;
    setSaving(prev => new Set(prev).add(field));
    setErrors(prev => ({ ...prev, [field]: undefined }));
    try {
      const updated = await patchScene(slug, scene.index, { [field]: newValue });
      onPatch(scene.index, updated);
    } catch (e) {
      if (isNetworkFailure(e)) {
        // Queue for retry on reconnect.
        retryQueue.push({
          slug, sceneIndex: scene.index, field, value: newValue,
          onAck: (updated) => {
            onPatch(scene.index, updated);
            setErrors(prev => ({ ...prev, [field]: undefined }));
          },
          onGiveUp: (msg) => {
            setErrors(prev => ({ ...prev, [field]: msg }));
          },
        });
        setErrors(prev => ({ ...prev, [field]: "offline — will retry on reconnect" }));
        return;
      }
      const msg = e instanceof ApiError
        ? `HTTP ${e.status}${(e.detail as { detail?: string })?.detail ? `: ${(e.detail as { detail: string }).detail}` : ""}`
        : String(e);
      setErrors(prev => ({ ...prev, [field]: msg }));
    } finally {
      setSaving(prev => {
        const next = new Set(prev);
        next.delete(field);
        return next;
      });
    }
  }, [scene.index, slug, onPatch, savedValues]);

  const badgeFor = (f: EditableField) => {
    if (saving.has(f)) return <span className="field-badge saving" aria-label="saving">…</span>;
    if (errors[f]) return <span className="field-badge error" title={errors[f]} aria-label="save failed">!</span>;
    if (isDirty(f)) return <span className="field-badge dirty" aria-label="unsaved">•</span>;
    return null;
  };

  const timeRange = `[${scene.start_s.toFixed(1)}s – ${scene.end_s.toFixed(1)}s]`;
  const selectedWords = selection && transcriptWords
    ? transcriptWords.slice(selection.start, selection.end + 1)
    : [];
  const selectedText = selectedWords.map(w => w.text).join(" ");
  const selectedCorrectionId = selectedWords.find(w => w.correction_id != null)?.correction_id ?? null;
  const canEditTranscript = selectedWords.length > 0;

  const applyTranscriptResponse = useCallback((resp: TranscriptResponse) => {
    void setTranscriptResponse(resp);
    updateSelection(null);
    onPatch(scene.index, { ...scene, target_text: resp.target_text });
  }, [onPatch, scene, setTranscriptResponse, updateSelection]);

  const seekToWordSelection = useCallback((nextSelection: { start: number; end: number }) => {
    if (!transcriptWords) return;
    const first = transcriptWords.find(w => w.word_index === Math.min(nextSelection.start, nextSelection.end));
    if (!first) return;
    onSeekToTime(first.start_s);
  }, [onSeekToTime, transcriptWords]);

  useEffect(() => {
    if (!current) return;
    const onKeyDown = async (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "z") return;
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName?.toLowerCase();
      if (tagName === "input" || tagName === "textarea" || tagName === "select" || target?.isContentEditable) {
        return;
      }
      event.preventDefault();
      try {
        const resp = event.shiftKey
          ? await redoTranscriptCorrection(slug)
          : await undoTranscriptCorrection(slug);
        if (resp.scene_index === scene.index) {
          applyTranscriptResponse(resp);
        }
      } catch (e) {
        if (e instanceof ApiError && (e.detail as { code?: string })?.code?.startsWith("no_")) {
          return;
        }
        console.error("Transcript history update failed", e);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [applyTranscriptResponse, current, scene.index, slug]);

  const submitCorrection = async () => {
    if (!selection || !correctionModal) return;
    setCorrectionModal(prev => prev ? { ...prev, busy: true, error: null } : prev);
    try {
      const resp = await applyTranscriptCorrection(slug, scene.index, {
        start_word_index: selection.start,
        end_word_index: selection.end,
        text: correctionModal.text,
      });
      applyTranscriptResponse(resp);
      setCorrectionModal(null);
    } catch (e) {
      const msg = e instanceof ApiError ? `HTTP ${e.status}` : String(e);
      setCorrectionModal(prev => prev ? { ...prev, busy: false, error: msg } : prev);
    }
  };

  const revertSelection = async () => {
    if (selectedCorrectionId == null || !correctionModal) return;
    setCorrectionModal(prev => prev ? { ...prev, busy: true, error: null } : prev);
    try {
      const resp = await revertTranscriptCorrection(slug, scene.index, selectedCorrectionId);
      applyTranscriptResponse(resp);
      setCorrectionModal(null);
    } catch (e) {
      const msg = e instanceof ApiError ? `HTTP ${e.status}` : String(e);
      setCorrectionModal(prev => prev ? { ...prev, busy: false, error: msg } : prev);
    }
  };

  return (
    <div
      className={`scene-row${current ? " current" : ""}${expanded ? " expanded" : " collapsed"}`}
      role="article"
      data-scene-index={scene.index}
    >
      <div
        className="scene-header"
        onClick={event => {
          if ((event.target as HTMLElement).closest(".scene-title")) return;
          onSceneClick(scene.index);
        }}
      >
        <button
          type="button"
          className="expando"
          aria-label={expanded ? "collapse scene" : "expand scene"}
          aria-expanded={expanded}
          onClick={e => {
            e.stopPropagation();
            onToggleExpanded(scene.index);
          }}
        >
          {expanded ? "\u25BC" : "\u25B6"}
        </button>
        <h3
          className="scene-title"
          onDoubleClick={event => {
            event.stopPropagation();
            if (!expanded) onToggleExpanded(scene.index);
          }}
          title={expanded ? undefined : "Double-click to expand"}
        >
          <span className="scene-num">#{scene.index}</span>
          <span className="scene-title-text">{sceneSummary(scene.target_text)}</span>
        </h3>
        <div className="scene-header-chips">
          <StatusChip label="keyframe" state={kfState} />
          <StatusChip label="clip" state={clipState} />
        </div>
        <span className="scene-time">{timeRange}</span>
      </div>

      {expanded ? (
        <div className="scene-body">
          <div className="transcript-editor">
            <div className="transcript-editor-header">
              <label>Transcript</label>
              {transcriptWords && transcriptWords.length > 0 ? (
                <button
                  type="button"
                  onClick={() => setCorrectionModal({ text: selectedText, error: null, busy: false })}
                  disabled={!canEditTranscript}
                  title={canEditTranscript ? "Edit selected transcript words" : "Select transcript words first"}
                >
                  Edit…
                </button>
              ) : null}
            </div>
            <div className="transcript-words" aria-label="Transcript words">
              {transcriptLoading ? <span className="transcript-empty">Loading transcript…</span> : null}
              {!transcriptLoading && transcriptError ? (
                <span className="transcript-empty">Transcript failed to load</span>
              ) : null}
              {!transcriptLoading && transcriptWords && transcriptWords.length === 0 ? (
                <span className="transcript-empty">No transcript words</span>
              ) : null}
              {(transcriptWords ?? []).map(word => {
                const selected = selection
                  ? word.word_index >= selection.start && word.word_index <= selection.end
                  : false;
                return (
                  <button
                    key={word.id}
                    type="button"
                    className={`transcript-word${selected ? " selected" : ""}${word.correction_id ? " corrected" : ""}${word.warning ? " warning" : ""}`}
                    title={`${word.start_s.toFixed(2)}s – ${word.end_s.toFixed(2)}s${word.correction_id ? `\nOriginal: ${word.original_text}` : ""}${word.warning ? `\nWarning: ${word.warning}` : ""}`}
                    onMouseDown={event => {
                      if (event.button !== 0) return;
                      selectingRef.current = true;
                      updateSelection({ start: word.word_index, end: word.word_index });
                    }}
                    onMouseEnter={e => {
                      if (e.buttons !== 1 || !selectingRef.current) return;
                      updateSelection(selectionRef.current ? {
                        start: Math.min(selectionRef.current.start, word.word_index),
                        end: Math.max(selectionRef.current.start, word.word_index),
                      } : selectionRef.current);
                    }}
                    onMouseUp={() => {
                      selectingRef.current = false;
                      const nextSelection = selectionRef.current
                        ? {
                          start: Math.min(selectionRef.current.start, word.word_index),
                          end: Math.max(selectionRef.current.start, word.word_index),
                        }
                        : { start: word.word_index, end: word.word_index };
                      updateSelection(nextSelection);
                      seekToWordSelection(nextSelection);
                    }}
                    onClick={() => {
                      if (!selectionRef.current) {
                        updateSelection({ start: word.word_index, end: word.word_index });
                      }
                    }}
                  >
                    {word.text}
                  </button>
                );
              })}
            </div>
          </div>

          <label>Visual beat{badgeFor("beat")}</label>
          <textarea
            value={beat}
            onChange={e => setBeat(e.target.value)}
            onBlur={() => commit("beat", beat)}
            className={errors.beat ? "field-error" : ""}
          />

          <label>Subject focus{badgeFor("subject_focus")}</label>
          <input
            type="text"
            value={subject}
            onChange={e => setSubject(e.target.value)}
            onBlur={() => commit("subject_focus", subject)}
            className={errors.subject_focus ? "field-error" : ""}
          />

          <label>Camera intent{badgeFor("camera_intent")}</label>
          <select
            value={camera}
            onChange={e => { setCamera(e.target.value); commit("camera_intent", e.target.value); }}
            className={errors.camera_intent ? "field-error" : ""}
          >
            <option value="">(unset)</option>
            {cameraIntents.map(v => <option key={v} value={v}>{v}</option>)}
          </select>

          <label>
            Image prompt
            {badgeFor("image_prompt")}
            {scene.prompt_is_user_authored ? <span style={{ marginLeft: 6, color: "#c97330" }}>(hand-authored)</span> : null}
          </label>
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onBlur={() => commit("image_prompt", prompt)}
            style={{ minHeight: 60 }}
            className={errors.image_prompt ? "field-error" : ""}
          />

          <RegenActions
            slug={slug} sceneIndex={scene.index}
            song={song}
            scene={scene}
            onPatched={updated => onPatch(scene.index, updated)}
          />
        </div>
      ) : null}

      {correctionModal ? (
        <div className="dialog-backdrop" role="dialog" aria-modal="true">
          <div className="dialog transcript-correction-dialog">
            <h2>Edit transcript</h2>
            <label>Selected words</label>
            <input
              value={correctionModal.text}
              onChange={e => setCorrectionModal(prev => prev ? { ...prev, text: e.target.value } : prev)}
              autoFocus
            />
            {correctionModal.busy ? (
              <p className="dialog-status">Re-aligning words against the audio…</p>
            ) : null}
            {correctionModal.error ? (
              <p className="dialog-error">{correctionModal.error}</p>
            ) : null}
            <div className="actions">
              <button onClick={() => setCorrectionModal(null)} disabled={correctionModal.busy}>
                Cancel
              </button>
              {selectedCorrectionId != null ? (
                <button onClick={revertSelection} disabled={correctionModal.busy}>
                  Revert to original
                </button>
              ) : null}
              <button className="primary" onClick={submitCorrection} disabled={correctionModal.busy}>
                {correctionModal.busy ? "Working…" : "Make Correction"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
});

function RegenActions({
  slug, sceneIndex, song, scene, onPatched,
}: {
  slug: string;
  sceneIndex: number;
  song: SongDetail;
  scene: Scene;
  onPatched: (s: Scene) => void;
}) {
  const [confirm, setConfirm] = useState<null | "keyframe" | "clip">(null);
  const [blockedReason, setBlockedReason] = useState<string | null>(null);
  const [showTakes, setShowTakes] = useState(false);
  const [takes, setTakes] = useState<SceneTake[] | null>(null);
  const [takesLoading, setTakesLoading] = useState(false);
  const [takesError, setTakesError] = useState<string | null>(null);

  const fetchTakes = useCallback(async () => {
    setTakesLoading(true);
    setTakesError(null);
    try {
      const r = await listTakes(slug, sceneIndex);
      setTakes(r.takes);
    } catch (e) {
      setTakesError(String(e));
    } finally {
      setTakesLoading(false);
    }
  }, [slug, sceneIndex]);

  const onOpen = useCallback(() => {
    setShowTakes(s => !s);
    if (!showTakes && takes === null) void fetchTakes();
  }, [showTakes, takes, fetchTakes]);

  const openRegen = useCallback((kind: SceneArtefactKind) => {
    const gate = sceneGenerationGate(song, scene, kind);
    if (!gate.ok) {
      setBlockedReason(gate.reason);
      return;
    }
    setConfirm(kind);
  }, [scene, song]);

  const triggerRegen = useCallback(async (kind: SceneArtefactKind) => {
    try {
      await regenerateScene(slug, sceneIndex, kind);
    } catch (e) {
      alert(`Regen failed: ${String(e)}`);
    } finally {
      setConfirm(null);
    }
  }, [slug, sceneIndex]);

  const onPickTake = useCallback(async (take: SceneTake) => {
    try {
      const updated = await selectTake(slug, sceneIndex, take.id, take.artefact_kind);
      onPatched(updated);
    } catch (e) {
      alert(`Select take failed: ${String(e)}`);
    }
  }, [slug, sceneIndex, onPatched]);

  return (
    <>
      <div className="actions">
        <button onClick={() => openRegen("keyframe")} title="regenerate keyframe">
          ⟳ keyframe
        </button>
        <button onClick={() => openRegen("clip")} title="regenerate clip">
          ⟳ clip
        </button>
        <button onClick={onOpen} title="show takes for this scene">
          {showTakes ? "▾ takes" : "▸ takes"}
        </button>
      </div>

      {showTakes ? (
        <div className="takes-panel">
          {takesLoading ? <span>Loading takes…</span> : null}
          {takesError ? <span style={{ color: "#e06060" }}>{takesError}</span> : null}
          {takes && takes.length === 0 ? <span>(no takes yet)</span> : null}
          {takes && takes.length > 0 ? (
            <ul className="take-list">
              {takes.map(t => (
                <li key={t.id} className={t.is_selected ? "selected" : ""}>
                  <button onClick={() => onPickTake(t)}>
                    {t.is_selected ? "● " : "○ "}
                    [{t.artefact_kind}] run{t.source_run_id ?? "-"} ·{" "}
                    {t.quality_mode ?? "—"} ·{" "}
                    {new Date(t.created_at * 1000).toLocaleTimeString()}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {confirm ? (
        <div className="dialog-backdrop" role="dialog" aria-modal="true">
          <div className="dialog">
            <h2>Regenerate {confirm}?</h2>
            <p>
              This will enqueue a {confirm} regen for scene #{sceneIndex}.{" "}
              {confirm === "keyframe"
                ? "One Gemini image call (~$0.04, ~16s)."
                : "One LTX clip render (~110s wall time, no API cost)."}
            </p>
            <div className="actions">
              <button onClick={() => setConfirm(null)}>Cancel</button>
              <button className="primary" onClick={() => triggerRegen(confirm)}>
                Regenerate
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {blockedReason ? (
        <div className="dialog-backdrop" role="dialog" aria-modal="true">
          <div className="dialog">
            <h2>Generation not ready</h2>
            <p>{blockedReason}</p>
            <div className="actions">
              <button className="primary" onClick={() => setBlockedReason(null)}>OK</button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

export default function Storyboard({
  song, cameraIntents, playingSceneIdx, onSeekToScene, onSeekToTime, onPatch, activeRegens,
}: Props) {
  const lastUserScrollAt = useRef<number>(0);
  const containerRef = useRef<HTMLDivElement>(null);
  // Collapsed-by-default: every row in the song starts hidden. Users click
  // the expando to open one. Keyed by scene index.
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set());
  const toggleExpanded = useCallback((idx: number) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }, []);

  // Track user scroll gestures so we don't fight them. After the grace
  // period elapses we resume auto-scrolling the current scene into view.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = () => { lastUserScrollAt.current = Date.now(); };
    el.addEventListener("wheel", onWheel, { passive: true });
    el.addEventListener("touchmove", onWheel, { passive: true });
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchmove", onWheel);
    };
  }, []);

  // Replay queued retries when the browser reports back online, and warn
  // the user via beforeunload if they try to close the tab with pending
  // (in-flight or queued) edits.
  useEffect(() => {
    const onOnline = async () => {
      // Drain the queue; requeue entries that still fail.
      const drained = retryQueue.splice(0, retryQueue.length);
      for (const item of drained) {
        try {
          const updated = await patchScene(item.slug, item.sceneIndex, { [item.field]: item.value });
          item.onAck(updated);
        } catch (e) {
          if (isNetworkFailure(e)) {
            retryQueue.push(item);
          } else {
            const msg = e instanceof ApiError
              ? `HTTP ${e.status}`
              : String(e);
            item.onGiveUp(msg);
          }
        }
      }
    };
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (retryQueue.length > 0) {
        event.preventDefault();
        (event as BeforeUnloadEvent).returnValue = "";
      }
    };
    window.addEventListener("online", onOnline);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, []);

  // Scroll the current scene into view unless the user has scrolled recently.
  useEffect(() => {
    if (playingSceneIdx == null) return;
    const now = Date.now();
    if (now - lastUserScrollAt.current < SCROLL_OVERRIDE_MS) return;
    const row = containerRef.current?.querySelector<HTMLElement>(
      `[data-scene-index="${playingSceneIdx}"]`,
    );
    if (row && typeof row.scrollIntoView === "function") {
      row.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [playingSceneIdx]);

  const emptyActive = useRef<Set<ActiveArtefacts>>(new Set());
  const seekToTime = onSeekToTime ?? noopSeekToTime;

  return (
    <div className="storyboard" aria-label="Scene list" ref={containerRef}>
      {song.scenes.map(scene => (
        <SceneRow
          key={scene.index}
          slug={song.slug}
          song={song}
          scene={scene}
          cameraIntents={cameraIntents}
          current={scene.index === playingSceneIdx}
          onSceneClick={onSeekToScene}
          onSeekToTime={seekToTime}
          onPatch={onPatch}
          activeArtefacts={activeRegens?.[scene.index] ?? emptyActive.current}
          expanded={expanded.has(scene.index)}
          onToggleExpanded={toggleExpanded}
        />
      ))}
    </div>
  );
}
