import { test, expect } from "@playwright/test";

async function gotoEditor(page: import("@playwright/test").Page, slug: string) {
  await page.goto(`/songs/${slug}`);
  await page.locator(".preview audio").waitFor({ state: "attached" });
}

test.describe("Centralized workflow state", () => {
  test("blocked, running, stale, and historical failed actions render from backend state", async ({ page, request }) => {
    await gotoEditor(page, "fresh-song-nl");
    const blockedKeyframes = page.locator('[data-stage="keyframes"]');
    await expect(blockedKeyframes).toHaveAttribute("data-status", "blocked");
    await blockedKeyframes.locator("button").click();
    await expect(page.getByRole("tooltip")).toContainText(/world and storyboard/i);

    await request.post("/api/test-only/workflow-fixture", {
      data: { slug: "workflow-e2e" },
    });
    await gotoEditor(page, "workflow-e2e");

    const transcription = page.locator('[data-stage="transcription"]');
    await expect(transcription).toHaveAttribute("data-status", "running");
    await expect(transcription.locator(".stage-running-detail")).toContainText("Transcribing");
    await expect(transcription.locator(".stage-running-detail")).toContainText("0:01 / 0:02 processed");
    await expect(transcription.locator(".stage-running-detail")).not.toContainText("Aligning lyrics");

    const world = page.locator('[data-stage="world_brief"]');
    await expect(world).toHaveAttribute("data-status", "done");
    await expect(world.locator(".stage-indicator-glyph")).toHaveText("✓");
    await expect(page.getByRole("alert").filter({ hasText: /world generation failed/i })).toHaveCount(0);

    const keyframes = page.locator('[data-stage="keyframes"]');
    await expect(keyframes).toHaveAttribute("data-status", "pending");
    await expect(keyframes).toContainText(/regenerate stale keyframes/i);
  });
});
