import { test, expect } from "@playwright/test";

// Story 16 e2e — fresh-song modal renders against the real fresh-song-nl
// fixture (no filter, no abstraction, no world brief, no scenes), and the
// non-fresh tiny-song fixture still gets the destructive modal.

test.describe("Fresh-song setup modal", () => {
  test("fresh-song filter pick renders 'Set filter' setup modal", async ({ page }) => {
    await page.goto("/songs/fresh-song-nl");
    await page.locator(".topbar select").first().waitFor({ state: "attached" });
    await page.locator(".topbar select").first().selectOption({ label: "cyanotype" });
    await expect(page.getByRole("heading", { name: /set filter/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /set filter/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /apply change/i })).toHaveCount(0);
  });

  test("fresh-song abstraction pick renders 'Confirm abstraction change' modal", async ({ page }) => {
    await page.goto("/songs/fresh-song-nl");
    await page.locator(".topbar select").nth(1).waitFor({ state: "attached" });
    await page.locator(".topbar select").nth(1).selectOption({ value: "75" });
    await expect(page.getByRole("heading", { name: /confirm abstraction change/i })).toBeVisible();
  });

  test("non-fresh control: tiny-song filter pick still shows destructive 'Confirm filter change' modal", async ({ page }) => {
    await page.goto("/songs/tiny-song");
    await page.locator(".preview audio").waitFor({ state: "attached" });
    await page.locator(".topbar select").first().selectOption({ label: "cyanotype" });
    await expect(page.getByRole("heading", { name: /confirm filter change/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /apply change/i })).toBeVisible();
  });
});
