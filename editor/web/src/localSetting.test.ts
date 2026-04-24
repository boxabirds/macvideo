import { afterEach, describe, expect, it } from "vitest";
import { localGet, localSet } from "./localSetting";

afterEach(() => localStorage.clear());

describe("localSetting", () => {
  it("returns fallback when key missing", () => {
    expect(localGet("nope", 1, "hi")).toBe("hi");
  });

  it("round-trips a value at a version", () => {
    const ok = localSet("k", 1, { a: 1 });
    expect(ok).toEqual({ ok: true });
    expect(localGet("k", 1, { a: 0 })).toEqual({ a: 1 });
  });

  it("returns fallback when stored version differs", () => {
    localSet("k", 1, "old");
    expect(localGet("k", 2, "fallback")).toBe("fallback");
  });

  it("returns fallback on corrupt JSON", () => {
    localStorage.setItem("k", "not-json{");
    expect(localGet("k", 1, "fallback")).toBe("fallback");
  });
});
