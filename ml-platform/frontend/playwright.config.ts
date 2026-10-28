import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { resolveE2ePython } from "./e2e/pythonExecutable";

const frontendDir = import.meta.dirname;
const backendDir = path.resolve(frontendDir, "../backend");
const portalFrontendDir = path.resolve(frontendDir, "../annotator/frontend");
const tempTestDir = path.resolve(frontendDir, "../../temp_test");
const e2eDatabaseUrl = `sqlite:///${path.join(tempTestDir, "playwright_e2e.db").replaceAll("\\", "/")}`;
const e2eArtifactDir = path.join(tempTestDir, "playwright-artifacts");
const e2eInferenceSecret = "playwright-inference-secret-at-least-32-bytes"; // gitleaks:allow
const e2eNotificationMasterKey = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="; // gitleaks:allow
const pythonExecutable = resolveE2ePython();
const pythonCommand = `"${pythonExecutable.replaceAll('"', '""')}"`;
const externalAcceptanceBaseUrl = process.env.WEEK12_ACCEPTANCE_BASE_URL?.trim();
const useExternalAcceptanceStack = process.env.RUN_WEEK12_BROWSER_ACCEPTANCE === "1";
const standardBaseUrl = process.env.PLAYWRIGHT_E2E_BASE_URL?.trim() || "http://127.0.0.1:5177";
const standardFrontendPort = Number(new URL(standardBaseUrl).port || "5177");
// Backend port is overridable so a locally occupied 8000 (docker stack, stray
// dev server) does not force the whole e2e run to serialize behind it.
// 默认 5177/8010 与 Week12 验收栈错开：栈发布 5173/8000（BACKEND_PORT=8000），
// 若同端口，ready 探测会被栈劫持，标准 e2e 实际打到 production 栈后端，
// 登录被 CORS_ORIGIN_FORBIDDEN 拒（2026-10-27 Chromium 全挂根因）。
const standardBackendPort = process.env.PLAYWRIGHT_E2E_BACKEND_PORT?.trim() || "8010";
const externalAcceptanceEvidenceDir = path.join(tempTestDir, "week11-12", "playwright");
const externalAcceptanceReportPath = path.join(
  externalAcceptanceEvidenceDir,
  "playwright-report.json",
);
const standardDatabaseUrl = process.env.DATABASE_URL?.trim() || e2eDatabaseUrl;
const standardArtifactDir = process.env.ARTIFACT_STORAGE_DIR?.trim() || e2eArtifactDir;

if (useExternalAcceptanceStack && !externalAcceptanceBaseUrl) {
  throw new Error("WEEK12_ACCEPTANCE_BASE_URL is required for external Week 12 acceptance");
}

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: useExternalAcceptanceStack
    ? [["list"], ["json", { outputFile: externalAcceptanceReportPath }]]
    : process.env.CI
      ? [["github"], ["json", { outputFile: externalAcceptanceReportPath }]]
      : "list",
  outputDir: externalAcceptanceEvidenceDir,
  use: {
    // 外部地址仅在 Week12 栈模式下生效；标准回归段跑在栈启动之前，
    // 且作业级 env 会泄漏 WEEK12_ACCEPTANCE_BASE_URL——若无条件采用，
    // baseURL 会指向尚未存在/属于栈的 5173，与本地 webServer 端口错位。
    baseURL: useExternalAcceptanceStack ? externalAcceptanceBaseUrl : standardBaseUrl,
    trace: useExternalAcceptanceStack ? "on" : "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: useExternalAcceptanceStack ? undefined : [
    {
      command: `${pythonCommand} -m uvicorn app.main:app --host 127.0.0.1 --port ${standardBackendPort}`,
      cwd: backendDir,
      url: `http://127.0.0.1:${standardBackendPort}/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ...process.env,
        DATABASE_URL: standardDatabaseUrl,
        // Standard E2E owns a local SQLite/artifact fixture; do not inherit
        // the external acceptance job's MinIO settings from the CI process.
        ARTIFACT_STORAGE_BACKEND: "local",
        ARTIFACT_STORAGE_DIR: standardArtifactDir,
        INFERENCE_RUNTIME_URL: "http://127.0.0.1:7000",
        INFERENCE_INTERNAL_SECRET: e2eInferenceSecret,
        NOTIFICATION_MASTER_KEY: e2eNotificationMasterKey,
        // 每条 spec 各自登录一次；默认 5/15min 的登录 IP 限流在本地复用
        // uvicorn 的多轮运行下必然触顶（CI 作业级 env 同值，这里补齐本地）。
        LOGIN_IP_RATE_LIMIT_CAPACITY: "100",
        // 浏览器同源登录必带 Origin: <standardBaseUrl>。作业级 env 可能带
        // APP_MODE=production（week12 段需要）并被 ...process.env 继承进来，
        // production 分支不做 127.0.0.1 回环别名扩展 → 登录被 CORS_ORIGIN_FORBIDDEN
        // 拒。按实际 e2e 前端地址显式注入别名，两种 app_mode 下都进 allowed 集合。
        FRONTEND_ORIGIN_ALIASES: [
          new URL(standardBaseUrl).origin,
          "http://127.0.0.1:5173",
          "http://localhost:5173",
        ].join(","),
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
        DATABASE_URL: standardDatabaseUrl,
        ARTIFACT_STORAGE_BACKEND: "local",
        ARTIFACT_STORAGE_DIR: standardArtifactDir,
        INFERENCE_INTERNAL_SECRET: e2eInferenceSecret,
      },
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${standardFrontendPort}`,
      cwd: frontendDir,
      url: `${standardBaseUrl.replace(/\/$/, "")}/login`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ...process.env,
        // vite.config 的 /api 代理默认打 127.0.0.1:8000；标准 e2e 后端在
        // standardBackendPort（默认 8010），必须显式指过去
        VITE_API_PROXY_TARGET: `http://127.0.0.1:${standardBackendPort}`,
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5174",
      cwd: portalFrontendDir,
      url: "http://127.0.0.1:5174",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
