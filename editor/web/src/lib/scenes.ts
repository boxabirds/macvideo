import type { Scene } from "../types";

// Find the scene whose [start_s, end_s) range contains t. Falls back to the
// scene whose start_s or end_s is closest to t when t lies outside every
// range — keeps the viewer pane responsive when the playhead drifts past
// the song's last scene or into a between-scene gap.
export function findSceneAt(scenes: Scene[], t: number): Scene | null {
  if (scenes.length === 0) return null;
  for (const s of scenes) {
    if (t >= s.start_s && t < s.end_s) return s;
  }
  let best = scenes[0]!;
  let bestDist = Infinity;
  for (const s of scenes) {
    const d = Math.min(Math.abs(t - s.start_s), Math.abs(t - s.end_s));
    if (d < bestDist) { bestDist = d; best = s; }
  }
  return best;
}
