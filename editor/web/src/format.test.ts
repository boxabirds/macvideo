import { describe, expect, it } from "vitest";
import { assetUrl, formatBytes, formatDurationMS } from "./format";

describe("formatDurationMS", () => {
  it("formats whole seconds", () => {
    expect(formatDurationMS(72)).toBe("1:12");
    expect(formatDurationMS(0)).toBe("0:00");
    expect(formatDurationMS(228.6)).toBe("3:49");
  });

  it("returns em-dash for null/NaN", () => {
    expect(formatDurationMS(null)).toBe("—");
    expect(formatDurationMS(undefined)).toBe("—");
    expect(formatDurationMS(NaN)).toBe("—");
  });
});

describe("formatBytes", () => {
  it("formats across binary thresholds", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(2 * 1024 * 1024)).toBe("2.0 MB");
    expect(formatBytes(3 * 1024 * 1024 * 1024)).toBe("3.00 GB");
  });
});

describe("assetUrl", () => {
  it("rewrites absolute output paths under /assets/outputs", () => {
    expect(assetUrl("/Users/x/editor/data/outputs/foo/keyframes/kf.png"))
      .toBe("/assets/outputs/foo/keyframes/kf.png");
  });

  it("rewrites music paths under /assets/music", () => {
    expect(assetUrl("/Users/x/music/blackbird.wav"))
      .toBe("/assets/music/blackbird.wav");
  });

  it("leaves unknown paths untouched", () => {
    expect(assetUrl("/etc/hosts")).toBe("/etc/hosts");
  });

  it("rewrites temp-dir outputs paths (e2e fixture case)", () => {
    expect(assetUrl("/var/folders/x/outputs/tiny-song/keyframes/kf_1.png"))
      .toBe("/assets/outputs/tiny-song/keyframes/kf_1.png");
  });
});
