import { test, expect } from "@playwright/test";

async function generationFixture(request: import("@playwright/test").APIRequestContext, slug: string) {
  await request.post("/api/test-only/env", {
    data: { set: { EDITOR_GENERATION_PROVIDER: "fake" } },
  });
  await request.post("/api/test-only/workflow-fixture", {
    data: {
      slug,
      world_brief: null,
      sequence_arc: null,
      include_prompts: false,
      include_failed_runs: false,
    },
  });
}

async function song(request: import("@playwright/test").APIRequestContext, slug: string) {
  const response = await request.get(`/api/songs/${slug}`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

test.describe("Product-owned generation", () => {
  test("generates world, storyboard, and scene prompts from saved data", async ({ page, request }) => {
    const slug = "product-generation-e2e";
    await generationFixture(request, slug);

    await page.goto(`/songs/${slug}`);
    await page.locator(".preview audio").waitFor({ state: "attached" });

    await page.locator('[data-stage="world_brief"] button').click();
    await expect.poll(async () => (await song(request, slug)).world_brief)
      .toContain("Product world for product-generation-e2e");
    await page.reload();
    await page.locator('[data-stage="world_brief"] button').click();
    await expect(page.locator(".world-brief-textarea")).toHaveValue(/Product world/);
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Cancel" }).click();

    await page.locator('[data-stage="storyboard"] button').click();
    await expect.poll(async () => (await song(request, slug)).sequence_arc)
      .toContain("Product storyboard arc");
    await page.reload();
    const row = page.locator('.scene-row[data-scene-index="1"]');
    await row.locator(".expando").click();
    await expect(row.locator("textarea").nth(0)).toHaveValue(/Product beat 1/);

    await page.locator('[data-stage="image_prompts"] button').click();
    await expect.poll(async () => {
      const body = await song(request, slug);
      return body.scenes.every((scene: { image_prompt: string | null }) => Boolean(scene.image_prompt));
    }).toBeTruthy();
    await page.reload();
    const refreshed = page.locator('.scene-row[data-scene-index="1"]');
    await refreshed.locator(".expando").click();
    await expect(refreshed.locator("textarea").nth(1)).toHaveValue(/charcoal frame for scene 1/);
    await expect(page.locator("body")).toContainText(/world description/i);
  });

  test("shows model-response failures without historical script names", async ({ page, request }) => {
    const slug = "product-generation-failure-e2e";
    await request.post("/api/test-only/env", {
      data: { set: { EDITOR_GENERATION_PROVIDER: "malformed" } },
    });
    await request.post("/api/test-only/workflow-fixture", {
      data: {
        slug,
        world_brief: "world",
        sequence_arc: "arc",
        include_prompts: false,
        include_failed_runs: false,
      },
    });

    await page.goto(`/songs/${slug}`);
    await page.locator(".preview audio").waitFor({ state: "attached" });
    await page.locator('[data-stage="image_prompts"] button').click();

    await expect(page.getByRole("alert").filter({ hasText: /image prompt list/i }))
      .toBeVisible({ timeout: 10_000 });
    await expect(page.locator("body")).toContainText(/image prompts/i);

    await request.post("/api/test-only/env", {
      data: { set: { EDITOR_GENERATION_PROVIDER: "fake" } },
    });
  });
});
