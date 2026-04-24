import { test, expect } from "@playwright/test";

// Story 10 e2e: render-final button gate is enabled when keyframes complete.
// The POST-produces-finished-row path is covered by integration tests
// (test_pipeline_final + test_api_stages); triggering it from e2e would
// persist clip takes into the shared-backend temp dir and pollute state
// for subsequent tests (preview.viewer-swap + regen.takes-list).

const SONG_SLUG = "tiny-song";

test("render final button is enabled when keyframes are complete", async ({ page }) => {
  await page.goto(`/songs/${SONG_SLUG}`);
  await page.locator(".preview audio").waitFor({ state: "attached" });

  // The tiny-song fixture imports 2/2 keyframes, so render-final is ready.
  const btn = page.getByRole("button", { name: /Render final video/i });
  await expect(btn).toBeVisible();
  await expect(btn).toBeEnabled();
});
