import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { resolveE2ePython } from "./e2e/pythonExecutable";

const frontendDir = import.meta.dirname;
const backendDir = path.resolve(frontendDir, "../backend");
const tempTestDir = path.resolve(frontendDir, "../../temp_test");
const e2eDatabaseUrl = `sqlite:///${path.join(tempTestDir, "playwright_e2e.db").replaceAll("\\", "/")}`;
const e2eArtifactDir = path.join(tempTestDir, "playwright-artifacts");
const e2eInferenceSecret = "playwright-inference-secret-at-least-32-bytes"; // gitleaks:allow
const e2eNotificationMasterKey = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="; // gitleaks:allow
const pythonExecutable = resolveE2ePython();
const pythonCommand = `"${pythonExecutable.replaceAll('"', '""')}"`;
const externalAcceptanceBaseUrl = process.env.WEEK12_ACCEPTANCE_BASE_URL?.trim();
const useExternalAcceptanceStack = process.env.RUN_WEEK12_BROWSER_ACCEPTANCE === "1";
const externalAcceptanceEvidenceDir = path.join(tempTestDir, "week11-12", "playwright");
const externalAcceptanceReportPath = path.join(
  externalAcceptanceEvidenceDir,
  "playwright-report.json",
);

if (useExternalAcceptanceStack && !externalAcceptanceBaseUrl) {
  throw new Error("WEEK12_ACCEPTANCE_BASE_URL is required for external Week 12 acceptance");
}

process.env.DATABASE_URL = e2eDatabaseUrl;
process.env.ARTIFACT_STORAGE_DIR = e2eArtifactDir;

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: useExternalAcceptanceStack
    ? [["list"], ["json", { outputFile: externalAcceptanceReportPath }]]
    : process.env.CI ? "github" : "list",
  outputDir: externalAcceptanceEvidenceDir,
  use: {
    baseURL: externalAcceptanceBaseUrl || "http://127.0.0.1:5173",
    trace: useExternalAcceptanceStack ? "on" : "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: useExternalAcceptanceStack ? undefined : [
    {
      command: `${pythonCommand} -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
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
        NOTIFICATION_MASTER_KEY: e2eNotificationMasterKey,
      },
    },
    {
      command: `${pythonCommand} -m uvicorn app.inference_runtime.app:build_runtime_app --factory --host 127.0.0.1 --port 7000 --workers 1`,
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
