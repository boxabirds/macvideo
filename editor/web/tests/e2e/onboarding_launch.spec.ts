import { test, expect } from "@playwright/test";

test("known-good launcher opens the editor with isolated fixture data", async ({ page, request }) => {
  const health = await request.get("/healthz");
  expect(health.ok()).toBeTruthy();

  await page.goto("/");
  await expect(page.locator("body")).toContainText("tiny-song");

  const response = await request.get("/api/songs");
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  const serialized = JSON.stringify(body);
  const repoRoot = process.cwd().replace(/\/editor\/web$/, "");
  expect(serialized).not.toContain(`${repoRoot}/music`);
  expect(serialized).toContain("macvideo-e2e");
});
