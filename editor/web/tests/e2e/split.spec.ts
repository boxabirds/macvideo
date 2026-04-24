import { test, expect } from "@playwright/test";

// Story 6 e2e: drag separator + reload verifies the stored split is applied.
// Uses the tiny-song fixture; the editor route mounts SplitPane once the
// song detail fetch resolves.

const SONG_SLUG = "tiny-song";

async function gotoEditor(page: import("@playwright/test").Page) {
  await page.goto(`/songs/${SONG_SLUG}`);
  await page.locator(".preview audio").waitFor({ state: "attached" });
}

function parseLhsPx(editor: string | null): number {
  if (!editor) return NaN;
  const m = editor.match(/--lhs-px:\s*(\d+)px/);
  return m ? parseInt(m[1]!, 10) : NaN;
}

test.describe("SplitPane", () => {
  test("drag + reload persists the new split width", async ({ page }) => {
    // Seed a clean localStorage once; subsequent reloads must NOT re-clear it.
    await page.goto("/");
    await page.evaluate(() => localStorage.clear());
    await gotoEditor(page);
    const sep = page.locator(".split-sep");
    await expect(sep).toBeVisible();

    // Start width should be the default 480 (fresh localStorage).
    const before = await page.locator(".editor").getAttribute("style");
    expect(parseLhsPx(before)).toBe(480);

    const box = await sep.boundingBox();
    if (!box) throw new Error("separator has no bounding box");
    const startX = box.x + box.width / 2;
    const y = box.y + box.height / 2;

    // Drag right by 120px — lhs should grow to ~600px.
    await page.mouse.move(startX, y);
    await page.mouse.down();
    await page.mouse.move(startX + 120, y, { steps: 8 });
    await page.mouse.up();

    const after = await page.locator(".editor").getAttribute("style");
    const afterPx = parseLhsPx(after);
    expect(afterPx).toBeGreaterThanOrEqual(560);
    expect(afterPx).toBeLessThanOrEqual(640);

    // Reload and confirm the new width is restored.
    await page.reload();
    await page.locator(".preview audio").waitFor({ state: "attached" });
    const reloaded = await page.locator(".editor").getAttribute("style");
    const reloadedPx = parseLhsPx(reloaded);
    expect(reloadedPx).toBe(afterPx);
  });

  test("double-click on separator resets to the default", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() =>
      localStorage.setItem(
        "editor.split.lhsPx",
        JSON.stringify({ version: 1, value: 700 }),
      ),
    );
    await gotoEditor(page);
    const editor = page.locator(".editor");
    const before = await editor.getAttribute("style");
    expect(parseLhsPx(before)).toBe(700);

    await page.locator(".split-sep").dblclick();
    const after = await editor.getAttribute("style");
    expect(parseLhsPx(after)).toBe(480);
  });
});
