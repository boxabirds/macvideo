import "@testing-library/jest-dom/vitest";

function installMemoryStoragePrototype(): Storage {
  const data = new Map<string, string>();
  Object.defineProperties(Storage.prototype, {
    length: {
      configurable: true,
      get() {
        return data.size;
      },
    },
    clear: {
      configurable: true,
      writable: true,
      value() {
        data.clear();
      },
    },
    getItem: {
      configurable: true,
      writable: true,
      value(key: string) {
        return data.has(key) ? data.get(key)! : null;
      },
    },
    key: {
      configurable: true,
      writable: true,
      value(index: number) {
        return Array.from(data.keys())[index] ?? null;
      },
    },
    removeItem: {
      configurable: true,
      writable: true,
      value(key: string) {
        data.delete(key);
      },
    },
    setItem: {
      configurable: true,
      writable: true,
      value(key: string, value: string) {
        data.set(key, String(value));
      },
    },
  });
  return Object.create(Storage.prototype) as Storage;
}

// Bun can expose a process-level localStorage object that is not compatible
// with the browser Storage API. Tests exercise browser behavior, so install a
// deterministic in-memory Storage object on both global scopes.
const storage = installMemoryStoragePrototype();
Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  writable: true,
  value: storage,
});
if (typeof window !== "undefined") {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: storage,
  });
}
