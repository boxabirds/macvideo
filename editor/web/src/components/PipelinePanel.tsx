// Story 9 (UI surface) — pipeline stage buttons.
// Actual stage execution requires backend routes that are out of this
// initial implementation's scope; buttons are wired but disabled with a
// tooltip explaining what each one will do.
import type { SongDetail, StageStatus } from "../types";

const STAGES = [
  { key: "transcription", label: "lyric alignment" },
  { key: "world_brief",   label: "world description" },
  { key: "storyboard",    label: "storyboard" },
  { key: "image_prompts", label: "image prompts" },
  { key: "keyframes",     label: "keyframes" },
] as const;

export default function PipelinePanel({ song, status }: { song: SongDetail; status: StageStatus }) {
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
        return (
          <div key={stage.key} className={`pipeline-stage ${state}`}>
            <span className="label">{stage.label}{summary}</span>
            <button disabled title={`story 9 — run ${stage.label} (backend stages not yet implemented)`}>▶</button>
          </div>
        );
      })}
    </div>
  );
}
