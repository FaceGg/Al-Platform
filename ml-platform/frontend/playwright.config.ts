import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const frontendDir = import.meta.dirname;
const backendDir = path.resolve(frontendDir, "../backend");
const tempTestDir = path.resolve(frontendDir, "../../temp_test");

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
        DATABASE_URL: `sqlite:///${path.join(tempTestDir, "playwright_e2e.db").replaceAll("\\", "/")}`,
        ARTIFACT_STORAGE_DIR: path.join(tempTestDir, "playwright-artifacts"),
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
