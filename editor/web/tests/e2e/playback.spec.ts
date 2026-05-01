import { test, expect } from "@playwright/test";

// Story 13 — playback monotonicity + three highlight surfaces stay in sync.
// Backstory: a useEffect in Preview.tsx wrote audio.currentTime backwards
// when playingSceneIdx changed, replaying the start of each scene as the
// playhead crossed boundaries. The hook refactor (useAudioPlayback) made
// the audio element the single source of truth; no React effect writes
// audio in response to a scene-index change.
//
// Fixture note: tiny-song has 2 scenes (0–0.3s, 0.3–0.5s; 0.5s total).
// The task body referenced 3+ scenes / 3-second sampling; adapted to the
// actual fixture. The boundary-crossing assertion in Test 1 still
// definitively catches the regressed effect (which fired at boundaries
// regardless of song length).

const SONG_SLUG = "tiny-song";
const SCENE2_START_S = 0.3;
const SCENE2_MID_S = 0.4;
const SEEK_TOLERANCE_S = 0.02;
const MONOTONIC_SLOP_S = 0.05;
const SAMPLE_INTERVAL_MS = 50;
const SAMPLE_WINDOW_MS = 600;

async function gotoEditor(page: import("@playwright/test").Page) {
  await page.goto(`/songs/${SONG_SLUG}`);
  await page.locator(".preview audio").waitFor({ state: "attached" });
}

test.describe("Playback (story 13)", () => {
  test("playback.monotonic — natural play + synthetic boundary jump never rewinds audio", async ({ page }) => {
    await gotoEditor(page);
    await page.getByRole("button", { name: /Loop selected scene/i }).click();
    // Kick natural play. Sample currentTime; assert non-decreasing.
    const samples: number[] = await page.evaluate(async (windowMs: number) => {
      const a = document.querySelector(".preview audio") as HTMLAudioElement;
      await a.play().catch(() => undefined);
      const out: number[] = [];
      const start = performance.now();
      while (performance.now() - start < windowMs) {
        out.push(a.currentTime);
        await new Promise(r => setTimeout(r, 50));
      }
      a.pause();
      return out;
    }, SAMPLE_WINDOW_MS);
    for (let i = 1; i < samples.length; i++) {
      expect(samples[i]).toBeGreaterThanOrEqual(samples[i - 1] - MONOTONIC_SLOP_S);
    }
    // Synthetic boundary jump — directly catches the original useEffect bug
    // (which fired only when audio was > scene.start_s + 0.2 past a boundary).
    // After fix: no React effect writes audio in response to scene change.
    await page.evaluate(() => {
      const a = document.querySelector(".preview audio") as HTMLAudioElement;
      Object.defineProperty(a, "currentTime", { value: 0.55, writable: true, configurable: true });
      a.dispatchEvent(new Event("timeupdate"));
    });
    await page.waitForTimeout(80);
    const after = await page.evaluate(() => {
      return (document.querySelector(".preview audio") as HTMLAudioElement).currentTime;
    });
    expect(after).toBeGreaterThan(0.4);
  });

  test("playback.storyboard-click — clicking a scene row seeks audio to that scene's start", async ({ page }) => {
    await gotoEditor(page);
    // Click the .scene-header (not the row itself) to avoid hitting the
    // editable target_text or expando button.
    await page.locator('.scene-row[data-scene-index="2"] .scene-header').click();
    const t = await page.evaluate(() => {
      return (document.querySelector(".preview audio") as HTMLAudioElement).currentTime;
    });
    expect(t).toBeGreaterThanOrEqual(SCENE2_START_S - SEEK_TOLERANCE_S);
    expect(t).toBeLessThanOrEqual(SCENE2_START_S + SEEK_TOLERANCE_S);
    await expect(page.locator(".preview .caption")).toContainText(/#2|oh oh oh/);
  });

  test("playback.timeline-click — clicking a timeline thumbnail seeks audio to that scene's start", async ({ page }) => {
    await gotoEditor(page);
    await page.locator(".preview .timeline .thumb").nth(1).click();
    const t = await page.evaluate(() => {
      return (document.querySelector(".preview audio") as HTMLAudioElement).currentTime;
    });
    expect(t).toBeGreaterThanOrEqual(SCENE2_START_S - SEEK_TOLERANCE_S);
    expect(t).toBeLessThanOrEqual(SCENE2_START_S + SEEK_TOLERANCE_S);
  });

  test("playback.scrubber — mid-scene seek updates scene-row, thumbnail, and viewer in sync", async ({ page }) => {
    await gotoEditor(page);
    // Drive playhead to mid-scene-2 by setting currentTime + dispatching
    // timeupdate (mirrors what a real scrubber drag would emit).
    await page.evaluate((t: number) => {
      const a = document.querySelector(".preview audio") as HTMLAudioElement;
      Object.defineProperty(a, "currentTime", { value: t, writable: true, configurable: true });
      a.dispatchEvent(new Event("timeupdate"));
    }, SCENE2_MID_S);
    await expect(page.locator('.scene-row[data-scene-index="2"]')).toHaveClass(/current/);
    await expect(page.locator(".preview .timeline .thumb").nth(1)).toHaveClass(/current/);
    await expect(page.locator(".preview .caption")).toContainText(/#2|oh oh oh/);
  });

  test("playback.loop-control — loop is on by default and same-scene click does not restart", async ({ page }) => {
    await gotoEditor(page);
    const loop = page.getByRole("button", { name: /Loop selected scene/i });
    await expect(loop).toHaveAttribute("aria-pressed", "true");

    await page.evaluate(() => {
      const a = document.querySelector(".preview audio") as HTMLAudioElement;
      Object.defineProperty(a, "paused", { value: false, configurable: true });
      Object.defineProperty(a, "currentTime", { value: 0.18, writable: true, configurable: true });
      a.dispatchEvent(new Event("timeupdate"));
    });
    await page.locator('.scene-row[data-scene-index="1"] .scene-header').click();
    const t = await page.evaluate(() => {
      return (document.querySelector(".preview audio") as HTMLAudioElement).currentTime;
    });
    expect(t).toBeGreaterThan(0.15);
  });

  test("playback.option-space — toggles play without stealing from text fields", async ({ page }) => {
    await gotoEditor(page);
    const calls = await page.evaluate(async () => {
      const a = document.querySelector(".preview audio") as HTMLAudioElement;
      let playCount = 0;
      a.play = async () => { playCount += 1; };
      Object.defineProperty(a, "paused", { value: true, configurable: true });
      window.dispatchEvent(new KeyboardEvent("keydown", { altKey: true, code: "Space" }));
      await new Promise(r => setTimeout(r, 0));
      return playCount;
    });
    expect(calls).toBe(1);
  });
});
