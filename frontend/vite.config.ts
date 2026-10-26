/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";
import { configDefaults } from "vitest/config";

// In development the API runs separately (uvicorn or docker compose); these
// paths are forwarded to it, so the app always calls its own origin.
const api = process.env.API_URL ?? "http://localhost:8000";
const forwarded = ["/api", "/docs", "/openapi.json"];

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    // The Host header stays the app's, so the API knows the app's own pages (see the chat widget).
    proxy: Object.fromEntries(forwarded.map((path) => [path, { target: api }])),
  },
  test: {
    environment: "jsdom",
    // e2e/ holds the browser tests, run by Playwright (npm run e2e).
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});
