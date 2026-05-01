import { test, expect } from "@playwright/test";

// Story 8 e2e: quality-mode toggle opens a confirmation, applies on OK.

const SONG_SLUG = "tiny-song";

test("quality-mode change opens a cosmetic confirm + applies on OK", async ({ page }) => {
  await page.goto(`/songs/${SONG_SLUG}`);
  await page.locator(".preview audio").waitFor({ state: "attached" });

  const modeSelect = page.locator(".topbar select").first();
  await modeSelect.selectOption("final");
  await expect(page.getByRole("dialog")).toBeVisible();
  // The cosmetic branch copy.
  await expect(page.getByText(/No Gemini calls/i)).toBeVisible();
  await page.getByRole("button", { name: /apply change/i }).click();

  // The backend PATCH should update songs.quality_mode='final'.
  await expect.poll(async () => {
    const response = await page.request.get(
      `/api/songs/${SONG_SLUG}`,
    );
    const data = await response.json();
    return data.quality_mode;
  }).toBe("final");
});
