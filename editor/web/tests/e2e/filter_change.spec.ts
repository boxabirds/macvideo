import { test, expect } from "@playwright/test";

test.describe("FilterChangeModal shared capability", () => {
  test.afterEach(async ({ request }) => {
    await request.post("http://localhost:8000/api/test-only/reset-song", {
      data: { slug: "fresh-song-nl" },
    });
  });

  test("happy-path-destructive", async ({ page, request }) => {
    await page.goto("/songs/tiny-song");
    await page.locator(".preview audio").waitFor({ state: "attached" });

    await page.locator(".topbar select").first().selectOption({ label: "watercolour" });
    await expect(page.getByRole("heading", { name: /confirm filter change/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /apply change/i })).toBeVisible();
    await expect(page.getByText(/Gemini calls/i)).toBeVisible();

    await page.getByRole("button", { name: /apply change/i }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();

    await expect.poll(async () => {
      const res = await request.get("http://localhost:8000/api/songs/tiny-song/regen");
      const body = await res.json();
      return body.runs.some((r: { scope: string }) => r.scope === "song_filter");
    }).toBe(true);
  });

  test("happy-path-fresh-setup skips preview and applies", async ({ page, request }) => {
    const previewCalls: string[] = [];
    page.on("request", req => {
      if (req.url().includes("/preview-change")) previewCalls.push(req.url());
    });

    await page.goto("/songs/fresh-song-nl");
    await page.locator(".topbar select").first().waitFor({ state: "attached" });
    await page.locator(".topbar select").first().selectOption({ label: "watercolour" });

    await expect(page.getByRole("heading", { name: /set filter/i })).toBeVisible();
    await expect(page.getByText(/will start the pipeline/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /set filter/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /apply change/i })).toHaveCount(0);
    await expect(page.getByText(/will be marked stale/i)).toHaveCount(0);
    await expect(page.getByText(/\d+ keyframes/i)).toHaveCount(0);
    expect(previewCalls).toHaveLength(0);

    await page.getByRole("button", { name: /set filter/i }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();

    await expect.poll(async () => {
      const res = await request.get("http://localhost:8000/api/songs/fresh-song-nl/regen");
      const body = await res.json();
      return body.runs.some((r: { scope: string }) => r.scope === "song_filter");
    }).toBe(true);
    expect(previewCalls).toHaveLength(0);
  });
});
