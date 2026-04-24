// Versioned local-storage wrapper. Read returns defaults if unset/corrupt.
export type Versioned<T> = { version: number; value: T };

export function localGet<T>(key: string, version: number, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Versioned<T>;
    if (parsed?.version !== version) return fallback;
    return parsed.value;
  } catch {
    return fallback;
  }
}

export function localSet<T>(key: string, version: number, value: T): { ok: boolean } {
  try {
    localStorage.setItem(key, JSON.stringify({ version, value }));
    return { ok: true };
  } catch {
    return { ok: false };
  }
}
