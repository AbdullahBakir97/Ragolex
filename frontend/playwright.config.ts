import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

// End-to-end tests: the web app, the API and its database, with a stand-in
// model server (tools/fake_models.py), so no model account is needed.
const root = fileURLToPath(new URL("..", import.meta.url));
const python = process.env.PYTHON ?? "python";
const ci = !!process.env.CI;

const api = {
  DATABASE_URL: process.env.E2E_DATABASE_URL ?? "postgresql+asyncpg://mini_rag:mini_rag@localhost:5432/mini_rag_e2e",
  EMBEDDING_BASE_URL: "http://127.0.0.1:9999/v1",
  LLM_BASE_URL: "http://127.0.0.1:9999/v1",
  OPENAI_API_KEY: "unused",
  // The stand-in's vectors score lower than a real model's.
  ANSWER_MIN_SCORE: "0.05",
  FILES_DIR: join(tmpdir(), "mini-rag-e2e-files"),
  PATH: process.env.PATH ?? "",
};

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: ci,
  retries: 0,
  reporter: ci ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Pixel 7"] }, grep: /@phone/ },
  ],
  webServer: [
    {
      command: `${python} tools/fake_models.py --port 9999 --delay 0.01`,
      cwd: root,
      url: "http://127.0.0.1:9999/health",
      reuseExistingServer: !ci,
    },
    {
      command: `${python} -m alembic upgrade head && ${python} -m uvicorn mini_rag.main:app --port 8000`,
      cwd: root,
      env: api,
      url: "http://127.0.0.1:8000/api/v1/health",
      reuseExistingServer: !ci,
      timeout: 60_000,
    },
    {
      command: "npx vite --port 5173 --strictPort",
      env: { API_URL: "http://127.0.0.1:8000" },
      url: "http://localhost:5173",
      reuseExistingServer: !ci,
    },
  ],
});
