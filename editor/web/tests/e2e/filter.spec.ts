import { test, expect } from "@playwright/test";

// Story 11 e2e: filter changes with kind-driven modal rendering.
// Tests fresh-setup vs destructive kinds, preview parity, and Story 16 regression.

test.describe("Filter change kind classification", () => {
  test("destructive filter change: fetch estimate + render dialog + confirm", async ({ page }) => {
    await page.goto("/songs/tiny-song");
    await page.locator(".preview audio").waitFor({ state: "attached" });

    const filterSelect = page.locator(".topbar select").first();
    await filterSelect.selectOption({ label: "cyanotype" });

    // Destructive modal should render.
    await expect(page.getByRole("heading", { name: /confirm filter change/i })).toBeVisible();
    // Preview-change estimate should land and render Gemini calls.
    await expect(page.getByText(/Gemini calls/i)).toBeVisible({ timeout: 3000 });
    // Apply button (not "Set filter") should be visible.
    await expect(page.getByRole("button", { name: /apply change/i })).toBeVisible();

    // Cancel should dismiss the dialog.
    await page.getByRole("button", { name: /cancel/i }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
  });

  test("fresh-setup filter change: no preview fetch, friendly copy, 'Set filter' button", async ({ page }) => {
    await page.goto("/songs/fresh-song-nl");
    await page.locator(".topbar select").first().waitFor({ state: "attached" });

    const filterSelect = page.locator(".topbar select").first();
    await filterSelect.selectOption({ label: "cyanotype" });

    // Fresh-setup modal should render.
    await expect(page.getByRole("heading", { name: /set filter/i })).toBeVisible();
    // Friendly copy: "will start the pipeline".
    await expect(page.getByText(/will start the pipeline/)).toBeVisible();
    // Cost line shown (fixed $0.01).
    await expect(page.getByText(/\$0\.01/)).toBeVisible();
    // No "computing estimate…" or Gemini calls breakdown (no preview fetch needed).
    await expect(page.getByText(/computing estimate/)).not.toBeVisible();
    // "Set filter" button (not "Apply change").
    await expect(page.getByRole("button", { name: /set filter/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /apply change/i })).not.toBeVisible();

    // Cancel should dismiss the dialog.
    await page.getByRole("button", { name: /cancel/i }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
  });

  test("Story 16 regression: non-fresh tiny-song shows destructive 'Confirm change' not 'Set filter'", async ({ page }) => {
    await page.goto("/songs/tiny-song");
    await page.locator(".preview audio").waitFor({ state: "attached" });

    const filterSelect = page.locator(".topbar select").first();
    await filterSelect.selectOption({ label: "cyanotype" });

    // Should render destructive modal (not fresh-setup).
    await expect(page.getByRole("heading", { name: /confirm filter change/i })).toBeVisible();
    // Should NOT render fresh-setup modal.
    await expect(page.getByRole("heading", { name: /^set filter$/i })).not.toBeVisible();
    // Should show "Apply change" button.
    await expect(page.getByRole("button", { name: /apply change/i })).toBeVisible();
  });

  test("noop filter change: setting filter to current value does nothing", async ({ page }) => {
    await page.goto("/songs/tiny-song");
    await page.locator(".preview audio").waitFor({ state: "attached" });

    // tiny-song currently has filter "charcoal", so selecting it again is a noop.
    const filterSelect = page.locator(".topbar select").first();
    const currentValue = await filterSelect.inputValue();

    await filterSelect.selectOption({ label: currentValue });

    // No dialog should appear for a noop change.
    await expect(page.getByRole("dialog")).not.toBeVisible();
  });

  test("fresh-setup filter pick applies successfully and updates song state", async ({ page }) => {
    await page.goto("/songs/fresh-song-nl");
    await page.locator(".topbar select").first().waitFor({ state: "attached" });

    const filterSelect = page.locator(".topbar select").first();
    await filterSelect.selectOption({ label: "watercolour" });

    await expect(page.getByRole("heading", { name: /set filter/i })).toBeVisible();
    await page.getByRole("button", { name: /set filter/i }).click();

    // Dialog should close after successful apply.
    await expect(page.getByRole("dialog")).not.toBeVisible();
    // Filter select should now show the new value.
    await expect(filterSelect).toHaveValue("watercolour");
  });
});
