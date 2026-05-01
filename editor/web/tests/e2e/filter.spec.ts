import { test, expect } from "@playwright/test";

test.describe("World-owned visual language", () => {
  test.afterEach(async ({ request }) => {
    await request.post("http://localhost:8000/api/test-only/env", {
      data: { set: { EDITOR_GENERATION_PROVIDER: "fake" } },
    });
  });

  test("top bar does not expose separate filter or abstraction controls", async ({ page }) => {
    await page.goto("/songs/tiny-song");
    await page.locator(".preview audio").waitFor({ state: "attached" });

    await expect(page.locator(".topbar")).toContainText(/visual language:/i);
    await expect(page.locator(".topbar")).not.toContainText(/^filter:/i);
    await expect(page.locator(".topbar")).not.toContainText(/^abstraction:/i);
    await expect(page.locator(".topbar select")).toHaveCount(1);
  });

  test("first world generation chooses filter and abstraction together", async ({ page, request }) => {
    const slug = "visual-language-first-run";
    await request.post("http://localhost:8000/api/test-only/workflow-fixture", {
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
    await page.locator(".preview audio").waitFor({ state: "attached" });
    await page.locator('[data-stage="world_brief"] button').click();

    await expect(page.getByRole("heading", { name: /choose the visual language/i })).toBeVisible();
    const selects = page.getByRole("dialog").locator("select");
    await expect(selects.nth(1)).toHaveValue("0");
    await selects.first().selectOption("watercolour");
    await page.getByRole("button", { name: /confirm and run/i }).click();

    await expect(page.getByRole("dialog")).not.toBeVisible();
    await expect.poll(async () => {
      const response = await request.get(`http://localhost:8000/api/songs/${slug}`);
      const body = await response.json();
      return `${body.filter}:${body.abstraction}`;
    }).toBe("watercolour:0");
    await expect.poll(async () => {
      const response = await request.get(`http://localhost:8000/api/songs/${slug}/regen`);
      const body = await response.json();
      return body.runs.some((r: { scope: string }) => r.scope === "song_filter");
    }).toBe(true);
  });

  test("existing world changes visual language through world dialog confirmation", async ({ page, request }) => {
    const slug = "visual-language-existing-world";
    await request.post("http://localhost:8000/api/test-only/workflow-fixture", {
      data: { slug, include_failed_runs: false },
    });

    await page.goto(`/songs/${slug}`);
    await page.locator(".preview audio").waitFor({ state: "attached" });
    await page.locator('[data-stage="world_brief"] button').click();
    await page.getByRole("button", { name: /change visual language/i }).click();

    await expect(page.getByRole("heading", { name: /change the visual language/i })).toBeVisible();
    await expect(page.getByText(/regenerates the world description, storyboard, scene prompts, and keyframes/i))
      .toBeVisible();
    const selects = page.getByRole("dialog").locator("select");
    await selects.first().selectOption("cyanotype");
    await page.getByRole("button", { name: /apply and regenerate/i }).click();

    await expect.poll(async () => {
      const response = await request.get(`http://localhost:8000/api/songs/${slug}`);
      const body = await response.json();
      return body.filter;
    }).toBe("cyanotype");
  });

  test("confirm and run saves visual language without HTTP error when generation provider is missing", async ({ page, request }) => {
    const slug = "visual-language-missing-provider";
    await request.post("http://localhost:8000/api/test-only/env", {
      data: { set: { EDITOR_GENERATION_PROVIDER: null, GEMINI_API_KEY: null } },
    });
    await request.post("http://localhost:8000/api/test-only/workflow-fixture", {
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
    await page.locator(".preview audio").waitFor({ state: "attached" });
    await page.locator('[data-stage="world_brief"] button').click();
    await page.getByRole("button", { name: /confirm and run/i }).click();

    await expect(page.getByRole("dialog")).not.toBeVisible();
    await expect(page.locator(".pipeline-error")).toContainText(/generation provider/i);
    await expect(page.locator(".pipeline-error")).not.toContainText(/HTTP 422/i);
    await expect.poll(async () => {
      const response = await request.get(`http://localhost:8000/api/songs/${slug}`);
      const body = await response.json();
      return `${body.filter}:${body.abstraction}`;
    }).toBe("oil impasto:0");
    await page.locator('[data-stage="world_brief"] button').click();
    await expect(page.getByRole("tooltip")).toContainText(/generation provider/i);
  });
});
