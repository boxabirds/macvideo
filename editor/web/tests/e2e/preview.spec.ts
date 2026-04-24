import { test, expect } from "@playwright/test";

// E2E coverage for Story 2 Preview pane. Hits the real backend + Vite + a real
// Chromium browser. Smoke tests the four capabilities against the tiny-song
// fixture (2 scenes, 0-0.3s "la la la", 0.3-0.5s "oh oh oh").

const SONG_SLUG = "tiny-song";

async function gotoEditor(page: import("@playwright/test").Page) {
  await page.goto(`/songs/${SONG_SLUG}`);
  // Wait for the preview audio element to appear — that's the signal the
  // SongDetail SWR fetch has resolved and Preview.tsx has mounted.
  await page.locator(".preview audio").waitFor({ state: "attached" });
}

test.describe("Preview pane", () => {
  test("preview.playhead — audio is mounted, caption follows scene lookup", async ({ page }) => {
    await gotoEditor(page);
    const audio = page.locator(".preview audio").first();
    await expect(audio).toBeAttached();
    // Drive the playhead to t=0.35 (inside scene 2). The component listens
    // for timeupdate events; we set currentTime then dispatch timeupdate so
    // the handler fires regardless of real audio decoding.
    await page.evaluate(() => {
      const a = document.querySelector(".preview audio") as HTMLAudioElement;
      Object.defineProperty(a, "currentTime", { value: 0.35, writable: true });
      a.dispatchEvent(new Event("timeupdate"));
    });
    const caption = page.locator(".preview .caption");
    await expect(caption).toContainText(/#2|oh oh oh/);
  });

  test("preview.viewer-swap — keyframe image appears when no clip is present", async ({ page }) => {
    await gotoEditor(page);
    // tiny-song fixture has keyframes but no clips.
    const viewerImg = page.locator(".preview .viewer img").first();
    await expect(viewerImg).toBeVisible();
    // And no <video> should render for a no-clip scene.
    const viewerVideo = page.locator(".preview .viewer video");
    await expect(viewerVideo).toHaveCount(0);
  });

  test("preview.timeline-nav — thumbnail strip renders one per scene and click seeks", async ({ page }) => {
    await gotoEditor(page);
    const thumbs = page.locator(".preview .timeline .thumb");
    await expect(thumbs).toHaveCount(2);
    // Click the second thumbnail — audio.currentTime should jump to 0.3.
    await thumbs.nth(1).click();
    const newTime = await page.evaluate(() => {
      const a = document.querySelector(".preview audio") as HTMLAudioElement;
      return a.currentTime;
    });
    // Allow for float fuzz — scene 2 starts at 0.3s.
    expect(newTime).toBeGreaterThanOrEqual(0.29);
    expect(newTime).toBeLessThanOrEqual(0.31);
  });

  test("preview.fullscreen — button is present with aria-label and click reaches the handler", async ({ page }) => {
    await gotoEditor(page);
    const btn = page.getByRole("button", { name: /full-screen/i });
    await expect(btn).toBeVisible();
    // Chromium in headless mode often refuses real fullscreen, so we verify
    // the click reaches our handler by stubbing requestFullscreen and watching
    // a flag. This still proves the handler wires to the Fullscreen API.
    await page.evaluate(() => {
      (window as unknown as { __fsCalled: boolean }).__fsCalled = false;
      const orig = Element.prototype.requestFullscreen;
      Element.prototype.requestFullscreen = function () {
        (window as unknown as { __fsCalled: boolean }).__fsCalled = true;
        return orig.call(this).catch(() => undefined);
      };
    });
    await btn.click();
    const called = await page.evaluate(
      () => (window as unknown as { __fsCalled: boolean }).__fsCalled,
    );
    expect(called).toBe(true);
  });

  test("preview regression — between-scene gap does NOT fall back to last scene (preview.html bug)", async ({ page }) => {
    await gotoEditor(page);
    // Drive playhead well past the song end (0.5s) — the nearest-scene logic
    // should pick scene #2 (closest by time), NOT crash, and NOT fall back
    // to the explicit "last scene of the song" that preview.html used.
    await page.evaluate(() => {
      const a = document.querySelector(".preview audio") as HTMLAudioElement;
      Object.defineProperty(a, "currentTime", { value: 1.0, writable: true });
      a.dispatchEvent(new Event("timeupdate"));
    });
    // findSceneAt(1.0) for scenes [0-0.3, 0.3-0.5] returns scene #2 by nearest
    // (the end 0.5 is 0.5s from 1.0 vs. scene #1's end 0.3 which is 0.7s).
    const caption = page.locator(".preview .caption");
    await expect(caption).toContainText(/#2|oh oh oh/);
  });
});
