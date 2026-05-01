import { test, expect } from "@playwright/test";

// Final render is gated by saved clip takes, not merely keyframes.

const SONG_SLUG = "tiny-song";

test("final-video segment is blocked until clips are complete", async ({ page }) => {
  await page.goto(`/songs/${SONG_SLUG}`);
  await page.locator(".preview audio").waitFor({ state: "attached" });

  // The tiny-song fixture imports keyframes but no selected clips, so the
  // product workflow keeps final rendering blocked until clips are rendered.
  const segment = page.locator('[data-stage="final_video"]');
  await expect(segment).toBeVisible();
  await expect(segment).toHaveAttribute("data-status", "blocked");
  const btn = segment.locator("button");
  await expect(btn).toHaveAttribute("title", "Render clips for every scene first.");
  await btn.click();
  await expect(page.getByRole("button", { name: "Render" })).toHaveCount(0);
});
