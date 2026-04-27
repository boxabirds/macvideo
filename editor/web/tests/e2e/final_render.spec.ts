import { test, expect } from "@playwright/test";

// Story 10 e2e: final-video segment is enabled when keyframes complete.
// Story 17 folded the standalone "Render final video" action into the
// pipeline breadcrumb; the gate semantics are unchanged. The
// POST-produces-finished-row path is covered by integration tests
// (test_pipeline_final + test_api_stages); triggering it from e2e would
// persist clip takes into the shared-backend temp dir and pollute state
// for subsequent tests (preview.viewer-swap + regen.takes-list).

const SONG_SLUG = "tiny-song";

test("final-video segment is enabled when keyframes are complete", async ({ page }) => {
  await page.goto(`/songs/${SONG_SLUG}`);
  await page.locator(".preview audio").waitFor({ state: "attached" });

  // The tiny-song fixture imports 2/2 keyframes, so the final-video segment
  // is in the "pending" state (prereqs done, not yet rendered) — clickable.
  const segment = page.locator('[data-stage="final_video"]');
  await expect(segment).toBeVisible();
  await expect(segment).toHaveAttribute("data-status", "pending");
  const btn = segment.locator("button");
  await expect(btn).toBeEnabled();
});
