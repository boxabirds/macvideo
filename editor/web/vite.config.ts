import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const webPort = Number(process.env.EDITOR_WEB_PORT ?? 5173);
const apiPort = process.env.EDITOR_API_PORT ?? "8000";
const apiTarget = `http://127.0.0.1:${apiPort}`;

export default defineConfig({
  plugins: [react()],
  server: {
    port: webPort,
    strictPort: true,
    proxy: {
      "/api":    { target: apiTarget, changeOrigin: true },
      "/assets": { target: apiTarget, changeOrigin: true },
      "/events": { target: apiTarget, changeOrigin: true, ws: true },
      "/healthz":{ target: apiTarget, changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
