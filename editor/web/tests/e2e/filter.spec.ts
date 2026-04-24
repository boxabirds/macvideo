import { test, expect } from "@playwright/test";

// Story 4 e2e: filter change dialog + preview-change estimate + confirm.

const SONG_SLUG = "tiny-song";

test.describe("Filter / abstraction chain", () => {
  test("changing the filter opens a dialog with an estimate and can be cancelled", async ({ page }) => {
    await page.goto(`/songs/${SONG_SLUG}`);
    await page.locator(".preview audio").waitFor({ state: "attached" });

    const filterSelect = page.locator(".topbar select").first();
    await filterSelect.selectOption({ label: "cyanotype" });

    await expect(page.getByRole("dialog")).toBeVisible();
    // Preview-change estimate should land and render Gemini calls info.
    await expect(page.getByText(/Gemini calls/i)).toBeVisible({ timeout: 3000 });

    await page.getByRole("button", { name: /cancel/i }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
  });
});
