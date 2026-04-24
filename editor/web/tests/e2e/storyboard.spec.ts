import { test, expect } from "@playwright/test";

// Story 3 e2e: edit a scene's beat inline, verify the patch reaches the
// backend (reload restores the edit), the hand-authored flag flips on
// image_prompt edits, and clicking a scene row seeks the preview.

const SONG_SLUG = "tiny-song";

async function gotoEditor(page: import("@playwright/test").Page) {
  await page.goto(`/songs/${SONG_SLUG}`);
  await page.locator(".preview audio").waitFor({ state: "attached" });
  await page.locator(".scene-row").first().waitFor({ state: "attached" });
}

test.describe("Storyboard", () => {
  test("edit beat, blur, reload, edit persists", async ({ page }) => {
    await gotoEditor(page);
    const row = page.locator('.scene-row[data-scene-index="1"]');
    const beat = row.locator("textarea").first();
    await beat.click();
    await beat.fill("e2e edit for scene 1");
    // Blur triggers PATCH
    await row.locator("input").first().click();
    // Give the PATCH round trip a moment to settle before reloading.
    await page.waitForTimeout(400);

    await page.reload();
    await page.locator(".preview audio").waitFor({ state: "attached" });
    const reloaded = page.locator('.scene-row[data-scene-index="1"] textarea').first();
    await expect(reloaded).toHaveValue("e2e edit for scene 1");
  });

  test("editing image_prompt surfaces the hand-authored indicator", async ({ page }) => {
    await gotoEditor(page);
    const row = page.locator('.scene-row[data-scene-index="2"]');
    // Fourth textarea block on this row = image prompt (beat first, then
    // subject input, then camera select, then prompt textarea).
    const prompt = row.locator("textarea").nth(1);
    await prompt.click();
    await prompt.fill("hand-written prompt for scene 2");
    await row.locator("input").first().click();
    await page.waitForTimeout(400);

    await page.reload();
    await page.locator(".preview audio").waitFor({ state: "attached" });
    const label = page.locator('.scene-row[data-scene-index="2"]')
      .locator("text=hand-authored");
    await expect(label).toBeVisible();
  });

  test("clicking a scene row seeks the preview to that scene", async ({ page }) => {
    await gotoEditor(page);
    // Click scene 2 row's header, which should fire onSelect → parent sets
    // currentIdx → Preview seeks audio.currentTime to scene 2's start_s
    // (0.3s in the tiny-song fixture).
    await page.locator('.scene-row[data-scene-index="2"] h3').click();
    const t = await page.evaluate(() => {
      const a = document.querySelector(".preview audio") as HTMLAudioElement;
      return a.currentTime;
    });
    expect(t).toBeGreaterThanOrEqual(0.29);
    expect(t).toBeLessThanOrEqual(0.31);
  });

  test("editing a beat marks the keyframe chip stale (staleness cascade, full stack)", async ({ page }) => {
    // State note: prior tests in this file may have already PATCHed scene 1,
    // so the "before" state of the chips is undefined — state lives in the
    // backend temp dir across the run. The test only asserts that AFTER
    // this PATCH, the stale classes are present (invariant regardless of
    // prior state, because the backend never clears stale on PATCH).
    await gotoEditor(page);
    const row = page.locator('.scene-row[data-scene-index="1"]');
    const beat = row.locator("textarea").first();
    const uniqueValue = `stale cascade trigger ${Date.now()}`;
    await beat.click();
    await beat.fill(uniqueValue);
    // Blur — PATCH fires, backend marks keyframe_stale + clip_stale, response
    // propagates through onPatch to SWR cache, row re-renders with .stale.
    await row.locator("input").first().click();

    const kfChip = row.locator(".chip.kf");
    await expect(kfChip).toHaveClass(/stale/, { timeout: 2000 });

    // Identity-chain cascade: scene 2 keyframe should also show stale
    // (but NOT scene 2 clip — identity chain doesn't affect clips).
    const row2kf = page.locator('.scene-row[data-scene-index="2"] .chip.kf');
    await expect(row2kf).toHaveClass(/stale/, { timeout: 2000 });
  });
});
