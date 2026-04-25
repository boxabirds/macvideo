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

const POLL_INTERVAL_MS = 2500;
const FAILED_BANNER_TIMEOUT_MS = 12_000;
const SCENES_LANDED_TIMEOUT_MS = 15_000;

async function gotoEditor(page: import("@playwright/test").Page, slug: string) {
  await page.goto(`/songs/${slug}`);
  await page.locator(".pipeline-panel").waitFor({ state: "visible" });
}

function transcribeRow(page: import("@playwright/test").Page) {
  return page.locator(".pipeline-stage").filter({ hasText: /lyric alignment/ });
}

test.describe("transcribe e2e", () => {
  test("happy_uncached: fresh song with lyrics → transcribe runs, scenes land", async ({ page }) => {
    await gotoEditor(page, "fresh-song-wl");

    const row = transcribeRow(page);
    await expect(row).toBeVisible();
    // Empty state — no scenes yet, no confirmation needed for the click.
    await row.locator("button").click();

    // Spinner appears within one SWR poll.
    await expect(row).toHaveClass(/running/, { timeout: POLL_INTERVAL_MS });

    // Eventually transcribes done — class drops back to a non-running state.
    await expect(row).not.toHaveClass(/running/, { timeout: SCENES_LANDED_TIMEOUT_MS });
    // No failed banner.
    await expect(page.locator(".transcribe-failed")).not.toBeVisible();

    // Scenes landed. Storyboard renders one row per scene; check via API
    // (UI selector is brittle; API is the source of truth for state).
    const detail = await page.request.get(
      "http://localhost:8000/api/songs/fresh-song-wl",
    );
    expect(detail.ok()).toBeTruthy();
    const body = await detail.json();
    expect(body.scenes.length).toBeGreaterThan(0);
  });

  test("blocked_missing_lyrics: preflight rejects, failed banner appears", async ({ page }) => {
    await gotoEditor(page, "fresh-song-nl");

    const row = transcribeRow(page);
    await row.locator("button").click();

    // Failed banner surfaces with the lyric-missing message.
    const banner = page.locator(".transcribe-failed");
    await expect(banner).toBeVisible({ timeout: FAILED_BANNER_TIMEOUT_MS });
    await expect(banner).toContainText(/fresh-song-nl\.txt/);
    await expect(banner.getByRole("button", { name: /Try again/i })).toBeVisible();

    // No scenes were created.
    const detail = await page.request.get(
      "http://localhost:8000/api/songs/fresh-song-nl",
    );
    expect(detail.ok()).toBeTruthy();
    const body = await detail.json();
    expect(body.scenes.length).toBe(0);
  });

  test("retry_from_failed: inject lyrics file then Try again succeeds", async ({ page }) => {
    await gotoEditor(page, "fresh-song-nl");

    // Reproduce the failure first.
    const row = transcribeRow(page);
    await row.locator("button").click();
    const banner = page.locator(".transcribe-failed");
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

    // Click Try again.
    await banner.getByRole("button", { name: /Try again/i }).click();
    // Banner dismisses optimistically.
    await expect(banner).not.toBeVisible({ timeout: 1000 });

    // Spinner appears, then drops back to non-running once done.
    await expect(row).toHaveClass(/running/, { timeout: POLL_INTERVAL_MS });
    await expect(row).not.toHaveClass(/running/, { timeout: SCENES_LANDED_TIMEOUT_MS });

    // Scenes now exist.
    const detail = await page.request.get(
      "http://localhost:8000/api/songs/fresh-song-nl",
    );
    const body = await detail.json();
    expect(body.scenes.length).toBeGreaterThan(0);
  });
});
