import { test, expect } from "@playwright/test";

// Story 18 e2e: fresh songs transcribe from audio through the browser and
// land scenes directly in the DB. The legacy manual-lyrics run button remains
// disabled for untranscribed songs so the UI cannot offer a failing action.

const SCENES_LANDED_TIMEOUT_MS = 15_000;

async function gotoEditor(page: import("@playwright/test").Page, slug: string) {
  await page.goto(`/songs/${slug}`);
  await page.locator(".pipeline-panel").waitFor({ state: "visible" });
}

function transcribeRow(page: import("@playwright/test").Page) {
  return page.locator(".pipeline-stage").filter({ hasText: /transcription/ });
}

function transcribeRunButton(page: import("@playwright/test").Page) {
  return transcribeRow(page).getByRole("button", { name: /Transcribe from audio/i });
}

async function fetchSong(page: import("@playwright/test").Page, slug: string) {
  const r = await page.request.get(`http://localhost:8000/api/songs/${slug}`);
  expect(r.ok()).toBeTruthy();
  return r.json();
}

test.describe("transcribe e2e", () => {
  test.afterEach(async ({ request }) => {
    await request.post("http://localhost:8000/api/test-only/reset-song", {
      data: { slug: "fresh-song-wl" },
    });
    await request.post("http://localhost:8000/api/test-only/reset-song", {
      data: { slug: "fresh-song-nl" },
    });
  });

  test("audio_with_lyrics_file: Transcribe from audio runs, scenes land", async ({ page }) => {
    await gotoEditor(page, "fresh-song-wl");

    // Pre-condition: empty song, no scenes.
    const before = await fetchSong(page, "fresh-song-wl");
    expect(before.scenes.length).toBe(0);

    await transcribeRunButton(page).click();
    await page.getByRole("button", { name: /^Start$/ }).click();

    // Wait for scenes to land. The queue may complete faster than the 2s SWR
    // poll cycle, so we don't assert on
    // the intermediate "running" class — just on the eventual outcome.
    await expect.poll(
      async () => (await fetchSong(page, "fresh-song-wl")).scenes.length,
      { timeout: SCENES_LANDED_TIMEOUT_MS, intervals: [500, 1000, 2000] },
    ).toBeGreaterThan(0);

    // No failed banner — the run completed successfully.
    await expect(page.locator(".transcribe-failed")).not.toBeVisible();
  });

  test("audio_only_no_lyrics_file: Transcribe from audio runs, scenes land", async ({ page }) => {
    await gotoEditor(page, "fresh-song-nl");

    const before = await fetchSong(page, "fresh-song-nl");
    expect(before.scenes.length).toBe(0);

    await transcribeRunButton(page).click();
    await page.getByRole("button", { name: /^Start$/ }).click();
    await expect.poll(
      async () => (await fetchSong(page, "fresh-song-nl")).scenes.length,
      { timeout: SCENES_LANDED_TIMEOUT_MS, intervals: [500, 1000, 2000] },
    ).toBeGreaterThan(0);
    await expect(page.locator(".transcribe-failed")).not.toBeVisible();
  });

  test("legacy run button is disabled before scenes exist", async ({ page }) => {
    await gotoEditor(page, "fresh-song-nl");
    await expect(transcribeRow(page).locator("button.stage-segment-btn")).toBeDisabled();
    await expect(transcribeRunButton(page)).toBeVisible();
  });
});
