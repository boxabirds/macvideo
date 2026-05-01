import { test, expect } from "@playwright/test";

test.describe("Visual language request flow", () => {
  test("combined first-run selection does not call preview-change or show old filter modal", async ({ page, request }) => {
    const slug = "visual-language-no-preview";
    const previewCalls: string[] = [];
    page.on("request", req => {
      if (req.url().includes("/preview-change")) previewCalls.push(req.url());
    });
    await request.post("/api/test-only/workflow-fixture", {
      data: {
        slug,
        filter: null,
        abstraction: null,
        world_brief: null,
        sequence_arc: null,
        include_prompts: false,
        include_takes: false,
        include_failed_runs: false,
      },
    });

    await page.goto(`/songs/${slug}`);
    await page.locator('[data-stage="world_brief"] button').click();

    await expect(page.getByRole("heading", { name: /choose the visual language/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: /set filter/i })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: /confirm filter change/i })).toHaveCount(0);
    expect(previewCalls).toHaveLength(0);
  });

  test("combined selection starts the visual-language chain once", async ({ page, request }) => {
    const slug = "visual-language-chain-once";
    await request.post("/api/test-only/workflow-fixture", {
      data: {
        slug,
        filter: null,
        abstraction: null,
        world_brief: null,
        sequence_arc: null,
        include_prompts: false,
        include_takes: false,
        include_failed_runs: false,
      },
    });

    await page.goto(`/songs/${slug}`);
    await page.locator('[data-stage="world_brief"] button').click();
    await page.getByRole("button", { name: /confirm and run/i }).click();

    await expect.poll(async () => {
      const response = await request.get(`/api/songs/${slug}/regen`);
      const body = await response.json();
      return body.runs.filter((r: { scope: string }) => r.scope === "song_filter").length;
    }).toBe(1);
  });
});
