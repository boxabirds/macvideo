import { test, expect } from "@playwright/test";

async function renderFixture(request: import("@playwright/test").APIRequestContext, slug: string) {
  await request.post("/api/test-only/env", {
    data: { set: { EDITOR_RENDER_PROVIDER: "fake" } },
  });
  await request.post("/api/test-only/workflow-fixture", {
    data: {
      slug,
      world_brief: "world",
      sequence_arc: "arc",
      include_prompts: true,
      include_takes: false,
      include_failed_runs: false,
    },
  });
}

async function song(request: import("@playwright/test").APIRequestContext, slug: string) {
  const response = await request.get(`/api/songs/${slug}`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

test("renders keyframes, clips, and final video from saved project data", async ({ page, request }) => {
  const slug = "product-render-e2e";
  await renderFixture(request, slug);
  await page.goto(`/songs/${slug}`);
  await page.locator(".preview audio").waitFor({ state: "attached" });

  await page.locator('[data-stage="keyframes"] button').click();
  await expect.poll(async () => {
    const body = await song(request, slug);
    return body.scenes.every((scene: { selected_keyframe_path: string | null }) => Boolean(scene.selected_keyframe_path));
  }).toBeTruthy();
  const afterKeyframes = await song(request, slug);
  const selectedKeyframes = afterKeyframes.scenes.map((scene: { selected_keyframe_path: string }) => scene.selected_keyframe_path);
  await expect(page.locator(".preview .viewer img")).toHaveAttribute("src", /_product_artifacts/);

  const rerenderResponse = await request.post(`/api/songs/${slug}/stages/keyframes`);
  expect(rerenderResponse.ok()).toBeTruthy();
  await expect.poll(async () => {
    const body = await song(request, slug);
    return body.scenes.map((scene: { selected_keyframe_path: string }) => scene.selected_keyframe_path);
  }).toEqual(selectedKeyframes);

  for (const idx of [1, 2]) {
    const response = await request.post(`/api/songs/${slug}/scenes/${idx}/takes`, {
      data: { artefact_kind: "clip", trigger: "regen" },
    });
    expect(response.ok()).toBeTruthy();
  }
  await expect.poll(async () => {
    const body = await song(request, slug);
    return body.scenes.every((scene: { selected_clip_path: string | null }) => Boolean(scene.selected_clip_path));
  }).toBeTruthy();
  await page.reload();
  await expect(page.locator(".preview .viewer video")).toHaveAttribute("src", /_product_artifacts/);

  await page.locator('[data-stage="final_video"] button').click();
  await page.getByRole("button", { name: "Render" }).click();
  await expect.poll(async () => {
    const response = await request.get(`/api/songs/${slug}/finished`);
    const body = await response.json();
    return body.finished.length;
  }).toBe(1);
  await expect.poll(async () => {
    const body = await song(request, slug);
    return body.workflow.stages.final_video.state;
  }).toBe("done");
  await page.reload();
  await expect(page.locator(".finished-list")).toContainText(/draft/i);
  await expect(page.locator("body")).toContainText(/final video/i);

  await request.post("/api/test-only/env", {
    data: { set: { EDITOR_RENDER_PROVIDER: "fail-final" } },
  });
  const failedRender = await request.post(`/api/songs/${slug}/render-final`);
  expect(failedRender.ok()).toBeTruthy();
  await expect.poll(async () => {
    const body = await song(request, slug);
    return body.workflow.stages.final_video.state;
  }).toBe("retryable");
  const finishedAfterFailure = await request.get(`/api/songs/${slug}/finished`);
  expect((await finishedAfterFailure.json()).finished.length).toBe(1);
  await page.reload();
  await expect(page.locator('[data-stage="final_video"]')).toHaveAttribute("data-status", "failed");
  await expect(page.locator(".finished-list")).toContainText(/draft/i);
  await request.post("/api/test-only/env", {
    data: { set: { EDITOR_RENDER_PROVIDER: "fake" } },
  });
});
