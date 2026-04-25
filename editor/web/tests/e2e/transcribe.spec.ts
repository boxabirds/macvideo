import { test, expect } from "@playwright/test";

// Story 12 e2e: full-stack transcribe through the browser.
// Backend runs against:
//   - fresh-song-wl  (audio + lyrics, no outputs/) → happy uncached path.
//   - fresh-song-nl  (audio only, no .txt) → preflight rejects, failed banner.
//   - fresh-song-nl + injected lyrics → Try again recovers.
//
// EDITOR_FAKE_WHISPERX_ALIGN points the transcribe stage at the fake
// whisperx_align so we don't pull torch/wav2vec2 into the e2e box.
//
// Note: the cached-POC-song case (fourth case in the task body) is proven
// at the integration level by editor/server/tests/test_transcribe_integration
// .py::test_transcribe_cached_song_skips_whisperx, since the browser-level
// signal is indistinguishable from the uncached path (both end at done) —
// only the absence of a fresh whisperx_cache write proves the skip, which
// is a backend concern, not a UI one.

const FAILED_BANNER_TIMEOUT_MS = 12_000;
const SCENES_LANDED_TIMEOUT_MS = 15_000;
const BANNER_DISMISS_TIMEOUT_MS = 2_000;

async function gotoEditor(page: import("@playwright/test").Page, slug: string) {
  await page.goto(`/songs/${slug}`);
  await page.locator(".pipeline-panel").waitFor({ state: "visible" });
}

function transcribeRow(page: import("@playwright/test").Page) {
  return page.locator(".pipeline-stage").filter({ hasText: /lyric alignment/ });
}

function transcribeRunButton(page: import("@playwright/test").Page) {
  // Scope to the run button (not the "Try again" button that lives inside
  // the failed banner of the same row).
  return transcribeRow(page).getByTitle(/^(Run|Re-run) lyric alignment/);
}

async function fetchSong(page: import("@playwright/test").Page, slug: string) {
  const r = await page.request.get(`http://localhost:8000/api/songs/${slug}`);
  expect(r.ok()).toBeTruthy();
  return r.json();
}

test.describe("transcribe e2e", () => {
  test("happy_uncached: fresh song with lyrics → transcribe runs, scenes land", async ({ page }) => {
    await gotoEditor(page, "fresh-song-wl");

    // Pre-condition: empty song, no scenes.
    const before = await fetchSong(page, "fresh-song-wl");
    expect(before.scenes.length).toBe(0);

    await transcribeRunButton(page).click();

    // Wait for scenes to land. The fake whisperx + real make_shots may
    // complete faster than the 2s SWR poll cycle, so we don't assert on
    // the intermediate "running" class — just on the eventual outcome.
    await expect.poll(
      async () => (await fetchSong(page, "fresh-song-wl")).scenes.length,
      { timeout: SCENES_LANDED_TIMEOUT_MS, intervals: [500, 1000, 2000] },
    ).toBeGreaterThan(0);

    // No failed banner — the run completed successfully.
    await expect(page.locator(".transcribe-failed")).not.toBeVisible();
  });

  test("blocked_missing_lyrics: preflight rejects, failed banner appears", async ({ page }) => {
    await gotoEditor(page, "fresh-song-nl");

    // If a previous test already failed this song, the failed banner is
    // already showing; skip the click in that case.
    const banner = page.locator(".transcribe-failed");
    if (!(await banner.isVisible().catch(() => false))) {
      await transcribeRunButton(page).click();
    }

    await expect(banner).toBeVisible({ timeout: FAILED_BANNER_TIMEOUT_MS });
    await expect(banner).toContainText(/fresh-song-nl\.txt/);
    await expect(banner.getByRole("button", { name: /Try again/i })).toBeVisible();

    const detail = await fetchSong(page, "fresh-song-nl");
    expect(detail.scenes.length).toBe(0);
  });

  test("retry_from_failed: inject lyrics file then Try again succeeds", async ({ page }) => {
    await gotoEditor(page, "fresh-song-nl");

    // Ensure a failed banner is present (from this run or a prior test).
    const banner = page.locator(".transcribe-failed");
    if (!(await banner.isVisible().catch(() => false))) {
      await transcribeRunButton(page).click();
    }
    await expect(banner).toBeVisible({ timeout: FAILED_BANNER_TIMEOUT_MS });

    // Inject a lyrics file via the test-only backend helper (mounted
    // when EDITOR_TEST_ENDPOINTS=1, which setup_backend.sh exports).
    const writeRes = await page.request.post(
      "http://localhost:8000/api/test-only/write-lyrics",
      {
        data: { slug: "fresh-song-nl", text: "now there is a line of lyric\nand a second\n" },
      },
    );
    expect(writeRes.ok()).toBeTruthy();

    // Click Try again. Banner dismisses optimistically.
    await banner.getByRole("button", { name: /Try again/i }).click();
    await expect(banner).not.toBeVisible({ timeout: BANNER_DISMISS_TIMEOUT_MS });

    // Scenes land within the alignment timeout.
    await expect.poll(
      async () => (await fetchSong(page, "fresh-song-nl")).scenes.length,
      { timeout: SCENES_LANDED_TIMEOUT_MS, intervals: [500, 1000, 2000] },
    ).toBeGreaterThan(0);
  });
});
