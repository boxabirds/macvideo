// Story 3 — storyboard LHS editor + story 5 per-scene regen buttons (stub
// until the backend regen routes land; UI is the visible surface).
import { memo, useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import type { Scene, SongDetail } from "../types";
import { fetcher, patchScene } from "../api";

function StatusChip({ label, state, stale }: { label: string; state: "grey" | "red" | "green" | "error"; stale: boolean }) {
  return <span className={`chip ${label} ${state}${stale && state === "green" ? " stale" : ""}`}>{label}</span>;
}

function classifyChips(scene: Scene) {
  const kf = scene.missing_assets.includes("keyframe")
    ? ("error" as const)
    : scene.selected_keyframe_path ? ("green" as const) : ("grey" as const);
  const clip = scene.missing_assets.includes("clip")
    ? ("error" as const)
    : scene.selected_clip_path ? ("green" as const) : ("grey" as const);
  return {
    kf, clip,
    kfStale: scene.dirty_flags.includes("keyframe_stale"),
    clipStale: scene.dirty_flags.includes("clip_stale"),
  };
}

type Props = {
  song: SongDetail;
  cameraIntents: string[];
  currentIdx: number | null;
  onSelect: (idx: number) => void;
  onPatch: (idx: number, updated: Scene) => void;
};

const SceneRow = memo(function SceneRow({
  scene, cameraIntents, current, onClick, onPatch, slug,
}: {
  scene: Scene;
  cameraIntents: string[];
  current: boolean;
  onClick: () => void;
  onPatch: (updated: Scene) => void;
  slug: string;
}) {
  // Per-field buffers so typing in one field doesn't re-render the others.
  const [beat, setBeat] = useState(scene.beat ?? "");
  const [subject, setSubject] = useState(scene.subject_focus ?? "");
  const [prompt, setPrompt] = useState(scene.image_prompt ?? "");
  const [camera, setCamera] = useState(scene.camera_intent ?? "");

  // Keep buffers in sync when the scene prop changes (e.g., on refetch).
  useEffect(() => { setBeat(scene.beat ?? ""); }, [scene.beat]);
  useEffect(() => { setSubject(scene.subject_focus ?? ""); }, [scene.subject_focus]);
  useEffect(() => { setPrompt(scene.image_prompt ?? ""); }, [scene.image_prompt]);
  useEffect(() => { setCamera(scene.camera_intent ?? ""); }, [scene.camera_intent]);

  const chips = classifyChips(scene);

  const commit = useCallback(async (field: "beat" | "subject_focus" | "camera_intent" | "image_prompt", newValue: string) => {
    const currentValue = field === "beat" ? scene.beat
                       : field === "subject_focus" ? scene.subject_focus
                       : field === "camera_intent" ? scene.camera_intent
                       : scene.image_prompt;
    if ((currentValue ?? "") === newValue) return;
    try {
      const updated = await patchScene(slug, scene.index, { [field]: newValue });
      onPatch(updated);
    } catch (e) {
      console.error("patch failed", e);
    }
  }, [scene, slug, onPatch]);

  return (
    <div className={`scene-row${current ? " current" : ""}`} onClick={onClick} role="article">
      <h3>
        <span className="scene-num">#{scene.index}</span>
        <span>{scene.target_text}</span>
      </h3>

      <label>Beat</label>
      <textarea
        value={beat}
        onChange={e => setBeat(e.target.value)}
        onBlur={() => commit("beat", beat)}
      />

      <label>Subject focus</label>
      <input
        type="text"
        value={subject}
        onChange={e => setSubject(e.target.value)}
        onBlur={() => commit("subject_focus", subject)}
      />

      <label>Camera intent</label>
      <select
        value={camera}
        onChange={e => { setCamera(e.target.value); commit("camera_intent", e.target.value); }}
      >
        <option value="">(unset)</option>
        {cameraIntents.map(v => <option key={v} value={v}>{v}</option>)}
      </select>

      <label>
        Image prompt
        {scene.prompt_is_user_authored ? <span style={{ marginLeft: 6, color: "#c97330" }}>(hand-authored)</span> : null}
      </label>
      <textarea
        value={prompt}
        onChange={e => setPrompt(e.target.value)}
        onBlur={() => commit("image_prompt", prompt)}
        style={{ minHeight: 60 }}
      />

      <div className="chips">
        <StatusChip label="kf" state={chips.kf} stale={chips.kfStale} />
        <StatusChip label="clip" state={chips.clip} stale={chips.clipStale} />
      </div>

      <div className="actions">
        <button disabled title="story 5 — regenerate keyframe (requires backend regen.enqueue)">⟳ keyframe</button>
        <button disabled title="story 5 — regenerate clip (requires backend regen.enqueue)">⟳ clip</button>
      </div>
    </div>
  );
});

export default function Storyboard({ song, cameraIntents, currentIdx, onSelect, onPatch }: Props) {
  return (
    <div className="storyboard" aria-label="Scene list">
      {song.scenes.map(scene => (
        <SceneRow
          key={scene.index}
          slug={song.slug}
          scene={scene}
          cameraIntents={cameraIntents}
          current={scene.index === currentIdx}
          onClick={() => onSelect(scene.index)}
          onPatch={updated => onPatch(scene.index, updated)}
        />
      ))}
    </div>
  );
}
