import { test, expect } from "@playwright/test";

async function gotoEditor(page: import("@playwright/test").Page, slug: string) {
  await page.goto(`/songs/${slug}`);
  await page.locator(".preview audio").waitFor({ state: "attached" });
}

async function expandScene(page: import("@playwright/test").Page, index: number) {
  const row = page.locator(`.scene-row[data-scene-index="${index}"]`);
  await expect(row).toBeVisible();
  if (await row.evaluate(el => el.classList.contains("collapsed"))) {
    await row.locator(".expando").click();
  }
  return row;
}

test.describe("Saved scenes and transcript are authoritative", () => {
  test("opens saved scenes without old generated files and preserves corrected timing", async ({ page, request }) => {
    await request.post("/api/test-only/workflow-fixture", {
      data: { slug: "saved-scenes-e2e" },
    });

    await gotoEditor(page, "saved-scenes-e2e");
    await expect(page.locator(".pipeline-error")).toHaveCount(0);
    const row = await expandScene(page, 1);
    await expect(row).toContainText("line 1");
    await expect(row.locator(".transcript-word", { hasText: "line" })).toBeVisible();

    await row.locator(".transcript-word", { hasText: "line" }).click();
    await row.getByRole("button", { name: /Edit/i }).click();
    await page.getByRole("dialog").locator("input").fill("fixed lyric");
    await page.getByRole("button", { name: /Make Correction/i }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 3000 });
    await expect(row.locator(".transcript-word", { hasText: "fixed" })).toBeVisible();

    await row.locator(".transcript-word", { hasText: "fixed" }).click();
    const t = await page.evaluate(() => {
      const audio = document.querySelector(".preview audio") as HTMLAudioElement;
      return audio.currentTime;
    });
    expect(t).toBeGreaterThanOrEqual(-0.01);
    expect(t).toBeLessThanOrEqual(0.02);

    await page.reload();
    await page.locator(".preview audio").waitFor({ state: "attached" });
    const reloaded = await expandScene(page, 1);
    await expect(reloaded.locator(".transcript-word", { hasText: "fixed" })).toBeVisible();
    await expect(reloaded).not.toContainText(/shots\.json|storyboard\.json|image_prompts\.json/i);
  });

  test("song with no saved scenes shows the next action without historical-file errors", async ({ page }) => {
    await gotoEditor(page, "fresh-song-nl");
    await expect(page.locator(".scene-row")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Transcribe from audio/i })).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/shots\.json|storyboard\.json|image_prompts\.json/i);
  });
});
