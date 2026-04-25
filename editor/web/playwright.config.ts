import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command: "bash tests/e2e/setup_backend.sh",
      url: "http://localhost:8000/healthz",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      // Use vite-only (not `bun run dev`) so the dev launcher's port-killing
      // doesn't reap the backend that the webServer above just started.
      command: "bun run dev:vite-only",
      url: "http://localhost:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
});
