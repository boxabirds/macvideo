// Small pure formatters used across the UI.
export function formatDurationMS(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function assetUrl(absolutePath: string): string {
  // Backend serves files under /assets/outputs/* and /assets/music/* relative
  // to the configured roots (production uses pocs/29-full-song/outputs,
  // tests use a temp dir). Find the LAST occurrence of /outputs/ or /music/
  // and rebase onto the matching /assets/ prefix.
  const outIdx = absolutePath.lastIndexOf("/outputs/");
  if (outIdx >= 0) {
    return `/assets/outputs/${absolutePath.slice(outIdx + "/outputs/".length)}`;
  }
  const musicIdx = absolutePath.lastIndexOf("/music/");
  if (musicIdx >= 0) {
    return `/assets/music/${absolutePath.slice(musicIdx + "/music/".length)}`;
  }
  return absolutePath;
}
