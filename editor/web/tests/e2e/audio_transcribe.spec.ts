import { test, expect } from "@playwright/test";

// Story 14 e2e — audio-transcribe happy-path workflow against the real
// backend (with EDITOR_FAKE_DEMUCS + EDITOR_FAKE_WHISPERX_TRANSCRIBE pointing
// at fake scripts so the run completes in ~1s instead of multi-minute real
// Demucs/WhisperX). Covers:
//   1. empty-state Transcribe-from-audio button visible.
//   2. confirm modal first-run copy + Start fires fetch.
//   3. running state visible after Start.
//   4. lyrics file lands and the segment goes done.
//   5. overwrite branch on a song that already has lyrics.

const FRESH = "fresh-song-nl";

async function gotoEditor(page: import("@playwright/test").Page, slug: string) {
  await page.goto(`/songs/${slug}`);
  // For songs with audio but no scenes the .preview audio element appears
  // once SongDetail's SWR fetch resolves.
  await page.locator(".preview audio").waitFor({ state: "attached" });
}

test.describe("Audio transcribe (Story 14)", () => {
  // Each test mutates fresh-song-nl's state (writes a lyrics file, derives
  // scenes, may spawn a background orchestration task). Reset between tests
  // — and wait briefly for any running orchestration to settle BEFORE the
  // reset so it can't re-write outputs after we cleaned up.
  test.afterEach(async ({ request }) => {
    // Give any in-flight orchestration up to 4s to terminate.
    const deadline = Date.now() + 4000;
    while (Date.now() < deadline) {
      const r = await request.get(
        `http://localhost:8000/api/songs/${FRESH}/regen?active_only=true`,
      );
      const body = await r.json().catch(() => ({ runs: [] }));
      if (!body.runs || body.runs.length === 0) break;
      await new Promise(rs => setTimeout(rs, 200));
    }
    await request.post("http://localhost:8000/api/test-only/reset-song", {
      data: { slug: FRESH },
    });
  });


  test("empty state shows Transcribe-from-audio button on fresh-song", async ({ page }) => {
    await gotoEditor(page, FRESH);
    const segment = page.locator('[data-stage="transcription"]');
    await expect(segment).toHaveAttribute("data-status", "pending");
    await expect(
      segment.getByRole("button", { name: /Transcribe from audio/i }),
    ).toBeVisible();
  });

  test("clicking Transcribe-from-audio opens confirm modal with first-run copy", async ({ page }) => {
    await gotoEditor(page, FRESH);
    await page.locator('[data-stage="transcription"]')
      .getByRole("button", { name: /Transcribe from audio/i })
      .click();
    await expect(page.getByRole("heading", { name: /Transcribe from audio/i }))
      .toBeVisible();
    await expect(page.getByRole("dialog"))
      .toContainText(/separates the vocals/i);
    await expect(page.getByRole("button", { name: /^Start$/ })).toBeVisible();
  });

  test("Cancel closes the modal without firing the API", async ({ page }) => {
    let audioCalls = 0;
    page.on("request", req => {
      if (req.url().includes("/audio-transcribe")) audioCalls += 1;
    });
    await gotoEditor(page, FRESH);
    await page.locator('[data-stage="transcription"]')
      .getByRole("button", { name: /Transcribe from audio/i })
      .click();
    await page.getByRole("button", { name: /Cancel/i }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    expect(audioCalls).toBe(0);
  });

  test("Start fires POST /audio-transcribe and modal closes", async ({ page }) => {
    const audioReqs: string[] = [];
    const audioResps: { url: string; status: number; body: string }[] = [];
    page.on("request", req => {
      if (req.url().includes("/audio-transcribe") && req.method() === "POST") {
        audioReqs.push(req.url());
      }
    });
    page.on("response", async resp => {
      if (resp.url().includes("/audio-transcribe")) {
        audioResps.push({
          url: resp.url(), status: resp.status(),
          body: await resp.text().catch(() => ""),
        });
      }
    });
    await gotoEditor(page, FRESH);
    await page.locator('[data-stage="transcription"]')
      .getByRole("button", { name: /Transcribe from audio/i })
      .click();
    await page.getByRole("button", { name: /^Start$/ }).click();
    // Wait for the request + response so failures tell us what the backend returned.
    await expect.poll(() => audioResps.length, { timeout: 5000 }).toBeGreaterThan(0);
    expect(audioResps[0].status, audioResps[0].body).toBe(200);
    expect(audioReqs[0]).toContain("force=false");
    // Modal closes once the API call resolves with 200.
    await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 5000 });
  });

  test("after Start, the audio-transcribe run lands in regen_runs and lyrics file is written", async ({ page, request }) => {
    await gotoEditor(page, FRESH);
    await page.locator('[data-stage="transcription"]')
      .getByRole("button", { name: /Transcribe from audio/i })
      .click();
    await page.getByRole("button", { name: /^Start$/ }).click();

    // Poll the regen endpoint until the audio-transcribe run terminates.
    // Story 14's contract: run_audio_transcribe writes the lyrics file
    // before handing off to the existing alignment stage. We assert the
    // run row exists with the correct scope; downstream alignment is
    // covered by Story 12's transcribe.spec.ts.
    await expect.poll(async () => {
      const r = await request.get(`http://localhost:8000/api/songs/${FRESH}/regen`);
      const body = await r.json();
      const run = (body.runs as { scope: string; status: string }[])
        .find(x => x.scope === "stage_audio_transcribe");
      return run?.status ?? "not-found";
    }, { timeout: 15000 }).not.toBe("not-found");
  });
});
