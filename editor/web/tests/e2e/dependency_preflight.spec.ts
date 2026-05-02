import { test, expect } from "@playwright/test";

const SONG_SLUG = "tiny-song";

async function gotoEditor(page: import("@playwright/test").Page) {
  await page.goto(`/songs/${SONG_SLUG}`);
  await page.locator(".preview audio").waitFor({ state: "attached" });
}

test.describe("Dependency preflight", () => {
  test.afterEach(async ({ request }) => {
    await request.post("/api/test-only/env", {
      data: { set: { EDITOR_RENDER_PROVIDER: "fake" } },
    });
  });

  test("Playwright shows product-level dependency failure before generation starts", async ({ page }) => {
    await page.request.post("/api/test-only/env", {
      data: { set: { EDITOR_RENDER_PROVIDER: null } },
    });
    await gotoEditor(page);

    const keyframesRow = page.locator('[data-stage="keyframes"]');
    await expect(keyframesRow).toBeVisible();
    await keyframesRow.getByRole("button").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("button", { name: /^Regenerate$/i }).click();

    const error = page.locator(".pipeline-error").first();
    await expect(error).toContainText(/renderer_provider_missing|dependency_preflight_failed/i);
    await expect(error).toContainText(/configured product render adapter/i);
  });
});
