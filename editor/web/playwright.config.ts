import { defineConfig, devices } from "@playwright/test";

const apiPort = process.env.EDITOR_E2E_API_PORT ?? process.env.EDITOR_API_PORT ?? "18000";
const webPort = process.env.EDITOR_E2E_WEB_PORT ?? process.env.EDITOR_WEB_PORT ?? "15173";
const apiBase = `http://127.0.0.1:${apiPort}`;
const webBase = `http://localhost:${webPort}`;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: webBase,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command: "bash tests/e2e/setup_backend.sh",
      url: `${apiBase}/healthz`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      // Use vite-only (not `bun run dev`) so the dev launcher's port-killing
      // doesn't reap the backend that the webServer above just started.
      command: "bun run dev:vite-only",
      url: webBase,
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
