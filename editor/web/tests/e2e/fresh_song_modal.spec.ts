import { test, expect } from "@playwright/test";

test.describe("World visual-language modal", () => {
  test("untranscribed fresh song does not expose visual-language setup", async ({ page }) => {
    await page.goto("/songs/fresh-song-nl");
    const world = page.locator('[data-stage="world_brief"]');
    await world.getByRole("button").click();

    await expect(page.getByRole("heading", { name: /choose the visual language/i })).toHaveCount(0);
    await expect(page.getByRole("tooltip")).toContainText(/transcription/i);
  });

  test("transcribed song with missing visual language opens combined picker", async ({ page, request }) => {
    const slug = "visual-language-modal";
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
    await expect(page.getByRole("button", { name: /oil impasto.*Thick palette-knife paint/i }))
      .toBeVisible();
    await expect(page.getByRole("button", { name: /confirm and run/i })).toBeVisible();
  });

  test("top bar has no separate abstraction modal", async ({ page }) => {
    await page.goto("/songs/tiny-song");
    await page.locator(".preview audio").waitFor({ state: "attached" });

    await expect(page.locator(".topbar select")).toHaveCount(1);
    await expect(page.getByRole("heading", { name: /confirm abstraction change/i })).toHaveCount(0);
  });
});
