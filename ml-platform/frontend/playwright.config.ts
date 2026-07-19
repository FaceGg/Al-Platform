import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const frontendDir = import.meta.dirname;
const backendDir = path.resolve(frontendDir, "../backend");
const tempTestDir = path.resolve(frontendDir, "../../temp_test");
const e2eDatabaseUrl = `sqlite:///${path.join(tempTestDir, "playwright_e2e.db").replaceAll("\\", "/")}`;
const e2eArtifactDir = path.join(tempTestDir, "playwright-artifacts");
const e2eInferenceSecret = "playwright-inference-secret-at-least-32-bytes";

process.env.DATABASE_URL = e2eDatabaseUrl;
process.env.ARTIFACT_STORAGE_DIR = e2eArtifactDir;

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  outputDir: path.join(tempTestDir, "playwright-test-results"),
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "python -m uvicorn app.main:app --host 127.0.0.1 --port 8000",
      cwd: backendDir,
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ...process.env,
        DATABASE_URL: e2eDatabaseUrl,
        ARTIFACT_STORAGE_DIR: e2eArtifactDir,
        INFERENCE_RUNTIME_URL: "http://127.0.0.1:7000",
        INFERENCE_INTERNAL_SECRET: e2eInferenceSecret,
      },
    },
    {
      command: "python -m uvicorn app.inference_runtime.app:build_runtime_app --factory --host 127.0.0.1 --port 7000 --workers 1",
      cwd: backendDir,
      url: "http://127.0.0.1:7000/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ...process.env,
        DATABASE_URL: e2eDatabaseUrl,
        ARTIFACT_STORAGE_DIR: e2eArtifactDir,
        INFERENCE_INTERNAL_SECRET: e2eInferenceSecret,
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5173",
      cwd: frontendDir,
      url: "http://127.0.0.1:5173/login",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
