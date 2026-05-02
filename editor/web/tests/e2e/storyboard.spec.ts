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

// Rows collapse by default — expand the targeted row before interacting
// with its body fields.
async function expandRow(page: import("@playwright/test").Page, sceneIndex: number) {
  const row = page.locator(`.scene-row[data-scene-index="${sceneIndex}"]`);
  // Only click expando if the row is still collapsed.
  const isCollapsed = await row.evaluate(el => el.classList.contains("collapsed"));
  if (isCollapsed) {
    await row.locator(".expando").click();
  }
}

test.describe("Storyboard", () => {
  test("editing text survives progress-only background pipeline updates", async ({ page }) => {
    let regenCalls = 0;
    await page.route(`**/api/songs/${SONG_SLUG}/regen`, async route => {
      regenCalls += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          runs: [{
            id: 9001,
            scope: "scene_keyframe",
            song_id: 1,
            scene_id: 1,
            scene_index: 1,
            artefact_kind: "keyframe",
            status: "running",
            quality_mode: "draft",
            cost_estimate_usd: null,
            started_at: 1,
            ended_at: null,
            error: null,
            progress_pct: Math.min(99, regenCalls * 10),
            phase: "rendering",
            created_at: 1,
          }],
        }),
      });
    });
    await gotoEditor(page);
    await expandRow(page, 1);
    const row = page.locator('.scene-row[data-scene-index="1"]');
    const beat = row.locator("textarea").first();
    await beat.click();
    await beat.fill("draft survives background progress");

    await expect.poll(() => regenCalls, { timeout: 5000 }).toBeGreaterThan(1);
    await expect(beat).toHaveValue("draft survives background progress");
    await expect(beat).toBeFocused();
    await expect(row.locator(".chip.keyframe")).toHaveClass(/in_progress/);
  });

  test("edit beat, blur, reload, edit persists", async ({ page }) => {
    await gotoEditor(page);
    await expandRow(page, 1);
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
    await expandRow(page, 1);
    const reloaded = page.locator('.scene-row[data-scene-index="1"] textarea').first();
    await expect(reloaded).toHaveValue("e2e edit for scene 1");
  });

  test("editing image_prompt surfaces the hand-authored indicator", async ({ page }) => {
    await gotoEditor(page);
    await expandRow(page, 2);
    const row = page.locator('.scene-row[data-scene-index="2"]');
    // Second textarea on this row = image prompt (visual beat, prompt).
    const prompt = row.locator("textarea").nth(1);
    await prompt.click();
    await prompt.fill("hand-written prompt for scene 2");
    await row.locator("input").first().click();
    await page.waitForTimeout(400);

    await page.reload();
    await page.locator(".preview audio").waitFor({ state: "attached" });
    await expandRow(page, 2);
    const label = page.locator('.scene-row[data-scene-index="2"]')
      .locator("text=hand-authored");
    await expect(label).toBeVisible();
  });

  test("clicking a scene row seeks the preview to that scene", async ({ page }) => {
    await gotoEditor(page);
    // Click scene 2 row's header, which should fire onSelect and seek audio.
    await page.locator('.scene-row[data-scene-index="2"] .scene-time').click();
    const t = await page.evaluate(() => {
      const a = document.querySelector(".preview audio") as HTMLAudioElement;
      return a.currentTime;
    });
    expect(t).toBeGreaterThanOrEqual(0.29);
    expect(t).toBeLessThanOrEqual(0.31);
  });

  test("double-clicking a collapsed scene title expands without seeking playback", async ({ page }) => {
    await gotoEditor(page);
    const row = page.locator('.scene-row[data-scene-index="2"]');
    await expect(row).toHaveClass(/collapsed/);
    await row.locator(".scene-title").dblclick();
    await expect(row).toHaveClass(/expanded/);
    const t = await page.evaluate(() => {
      const a = document.querySelector(".preview audio") as HTMLAudioElement;
      return a.currentTime;
    });
    expect(t).toBeLessThan(0.1);
  });

  test("selecting a transcript word seeks playback to that word", async ({ page }) => {
    await gotoEditor(page);
    await expandRow(page, 1);
    const row = page.locator('.scene-row[data-scene-index="1"]');
    const word = row.locator(".transcript-word").nth(1);
    const title = await word.getAttribute("title");
    const expectedStart = Number(title?.match(/^([0-9.]+)s/)?.[1]);
    await word.click();
    const t = await page.evaluate(() => {
      const a = document.querySelector(".preview audio") as HTMLAudioElement;
      return a.currentTime;
    });
    expect(t).toBeGreaterThanOrEqual(expectedStart - 0.02);
    expect(t).toBeLessThanOrEqual(expectedStart + 0.02);
  });

  test("editing a beat marks the keyframe chip stale (staleness cascade, full stack)", async ({ page }) => {
    // State note: prior tests in this file may have already PATCHed scene 1,
    // so the "before" state of the chips is undefined — state lives in the
    // backend temp dir across the run. The test only asserts that AFTER
    // this PATCH, the stale classes are present (invariant regardless of
    // prior state, because the backend never clears stale on PATCH).
    await gotoEditor(page);
    await expandRow(page, 1);
    const row = page.locator('.scene-row[data-scene-index="1"]');
    const beat = row.locator("textarea").first();
    const uniqueValue = `stale cascade trigger ${Date.now()}`;
    await beat.click();
    await beat.fill(uniqueValue);
    // Blur — PATCH fires, backend marks keyframe_stale + clip_stale, response
    // propagates through onPatch to SWR cache, row re-renders as pending.
    await row.locator("input").first().click();

    // After the cascade, the keyframe chip is in a non-"done" state
    // (pending means asset exists but is stale).
    const kfChip = row.locator(".chip.keyframe");
    await expect(kfChip).toHaveClass(/pending|error/, { timeout: 2000 });

    // Identity-chain cascade: scene 2 keyframe is also marked pending
    // (but NOT scene 2 clip — identity chain doesn't affect clips).
    const row2kf = page.locator('.scene-row[data-scene-index="2"] .chip.keyframe');
    await expect(row2kf).toHaveClass(/pending|error/, { timeout: 2000 });
  });

  test("edit transcript words through correction modal, reload, phrase persists separately from visual beat", async ({ page }) => {
    await gotoEditor(page);
    await expandRow(page, 1);
    const row = page.locator('.scene-row[data-scene-index="1"]');
    await expect(row).toContainText("Transcript");
    await expect(row).toContainText("Visual beat");
    const visualBeatBefore = await row.locator("textarea").first().inputValue();

    await row.locator(".transcript-word").first().click();
    await row.getByRole("button", { name: /Edit/i }).click();
    const corrected = `corrected ${Date.now()}`;
    await page.getByRole("dialog").locator("input").fill(corrected);
    await page.getByRole("button", { name: /Make Correction/i }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 3000 });

    await page.reload();
    await page.locator(".preview audio").waitFor({ state: "attached" });
    await expandRow(page, 1);
    const reloadedRow = page.locator('.scene-row[data-scene-index="1"]');
    for (const token of corrected.split(/\s+/)) {
      await expect(reloadedRow.locator(".transcript-word", { hasText: token })).toBeVisible();
    }
    await expect(reloadedRow.locator("textarea").first()).toHaveValue(visualBeatBefore);
  });
});
