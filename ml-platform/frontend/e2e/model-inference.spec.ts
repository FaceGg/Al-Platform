import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { resolveE2ePython } from "./pythonExecutable";

type SeededInferenceSources = {
  model_library_ids: string[];
};

type RolloutFixtureResult = {
  state: string;
  current_step: number;
};

const fixtureDatabaseUrl = process.env.DATABASE_URL?.trim() || `sqlite:///${path
  .resolve(import.meta.dirname, "../../../temp_test/playwright_e2e.db")
  .replaceAll("\\", "/")}`;

function runInferenceFixture<T>(name: string, ...args: string[]): T {
  const script = path.resolve(import.meta.dirname, "fixtures", name);
  return JSON.parse(execFileSync(resolveE2ePython(), [script, ...args], {
    encoding: "utf-8",
    env: {
      ...process.env,
      DATABASE_URL: fixtureDatabaseUrl,
      INFERENCE_RUNTIME_URL: "http://127.0.0.1:7000",
      INFERENCE_INTERNAL_SECRET: "playwright-inference-secret-at-least-32-bytes",
    },
  })) as T;
}

test("model registry production release lifecycle", async ({ page, browser }) => {
  const unique = Date.now();
  const projectName = `Inference E2E ${unique}`;
  const modelName = `Weld fault ${unique}`;
  const deploymentName = `line-${unique}`;
  const viewer = {
    username: `inference-viewer-${unique}`,
    password: "viewer-e2e-password",
  };

  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("admin");
  await page.getByPlaceholder("密码").fill("admin123");
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/$/);

  const viewerRegistration = await page.evaluate(async (candidate) => {
    const response = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(candidate),
    });
    return { status: response.status, body: await response.json() };
  }, viewer);
  expect(viewerRegistration.status).toBe(200);

  const projectResponse = await page.evaluate(async (name) => {
    const token = localStorage.getItem("token") || "";
    const response = await fetch("/api/projects", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ name, description: "Inference browser acceptance" }),
    });
    return { status: response.status, body: await response.json() };
  }, projectName);
  expect(projectResponse.status).toBe(201);
  const projectId = String(projectResponse.body.id);

  const membershipStatus = await page.evaluate(async ({ projectId, username }) => {
    const token = localStorage.getItem("token") || "";
    const response = await fetch(`/api/projects/${projectId}/members`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ username, role: "viewer" }),
    });
    return response.status;
  }, { projectId, username: viewer.username });
  expect(membershipStatus).toBe(201);

  const sources = runInferenceFixture<SeededInferenceSources>("seed_inference_model.py", projectId);
  expect(sources.model_library_ids).toHaveLength(2);
  const [v1SourceId, v2SourceId] = sources.model_library_ids;

  await page.goto("/models");
  await page.getByRole("combobox", { name: "项目" }).click();
  await page.getByText(new RegExp(projectName)).click();
  await page.getByRole("button", { name: "新建注册模型" }).click();
  const modelDialog = page.getByRole("dialog", { name: "新建注册模型" });
  await modelDialog.getByLabel("名称").fill(modelName);
  await modelDialog.getByRole("button", { name: "创建" }).click();

  const modelRow = page.getByRole("row", { name: new RegExp(modelName) });
  await expect(modelRow).toBeVisible();

  const registerAndApprove = async (sourceId: string, versionNumber: number) => {
    await modelRow.getByRole("button", { name: `注册版本 ${modelName}` }).click();
    const registerDialog = page.getByRole("dialog", { name: "注册版本" });
    await registerDialog.getByLabel("来源训练模型 ID").fill(sourceId);
    await registerDialog.getByRole("button", { name: "注册版本" }).click();

    await modelRow.getByRole("button", { name: `版本 ${modelName}`, exact: true }).click();
    const versionDrawer = page.getByRole("dialog", { name: `${modelName} 版本` });
    await versionDrawer.getByRole("button", { name: `批准 版本 ${versionNumber}` }).click();
    const versionRow = versionDrawer.getByRole("row").filter({ hasText: `v${versionNumber}` });
    await expect(versionRow.getByText("已批准")).toBeVisible();
    await versionDrawer.getByRole("button", { name: "Close" }).click();
  };

  await registerAndApprove(v1SourceId, 1);
  await registerAndApprove(v2SourceId, 2);

  await page.getByRole("tab", { name: "推理部署" }).click();
  await page.getByRole("button", { name: "新建部署" }).click();
  const deploymentDialog = page.getByRole("dialog", { name: "新建部署" });
  await deploymentDialog.locator("input#name").fill(deploymentName);
  await deploymentDialog.getByRole("combobox", { name: "* 版本" }).click();
  await page.getByText(`${modelName} v1`, { exact: true }).click();
  const deploymentResponsePromise = page.waitForResponse((response) =>
    response.request().method() === "POST"
    && response.url().includes(`/api/projects/${projectId}/inference-deployments`),
  );
  await deploymentDialog.getByRole("button", { name: "创建" }).click();
  const deploymentResponse = await deploymentResponsePromise;
  expect(deploymentResponse.status()).toBe(201);
  const deployment = await deploymentResponse.json() as { id: string };

  const deploymentRow = page.getByRole("row", { name: new RegExp(deploymentName) });
  await deploymentRow.getByRole("button", { name: `启动 ${deploymentName}` }).click();
  await expect(deploymentRow.getByText("运行中")).toHaveCount(2);

  const openOperations = async () => {
    await deploymentRow.getByRole("button", { name: `发布运维 ${deploymentName}` }).click();
    const drawer = page.getByRole("dialog", { name: `发布运维: ${deploymentName}` });
    await expect(drawer).toBeVisible();
    return drawer;
  };

  let operationsDrawer = await openOperations();
  await operationsDrawer.getByRole("button", { name: "新建发布" }).click();
  const rolloutDialog = page.getByRole("dialog", { name: "新建发布" });
  await rolloutDialog.getByRole("combobox", { name: "目标版本" }).click();
  await page.getByText(`${modelName} v2`, { exact: true }).click();
  const rolloutResponsePromise = page.waitForResponse((response) =>
    response.request().method() === "POST"
    && response.url().endsWith(`/api/inference-deployments/${deployment.id}/rollouts`),
  );
  await rolloutDialog.getByRole("button", { name: "创建" }).click();
  const rolloutResponse = await rolloutResponsePromise;
  expect(rolloutResponse.status()).toBe(201);
  const rollout = await rolloutResponse.json() as {
    id: string;
    state: string;
    targets: Array<{ weight_bps: number }>;
  };
  expect(rollout.state).toBe("pending");
  expect(rollout.targets).toEqual([expect.objectContaining({ weight_bps: 10000 })]);
  const pendingReleaseRow = operationsDrawer.getByRole("row").filter({ hasText: "待发布" });
  await expect(pendingReleaseRow).toContainText("100%");

  const preloaded = runInferenceFixture<RolloutFixtureResult>(
    "advance_inference_rollout.py",
    rollout.id,
    "preload",
  );
  expect(preloaded.state).toBe("progressing");
  await operationsDrawer.getByRole("button", { name: "Close" }).click();
  operationsDrawer = await openOperations();

  await operationsDrawer.getByRole("button", { name: "创建 API 密钥" }).click();
  const createdKeyDialog = page.getByRole("dialog", { name: "API 密钥已创建" });
  const plaintextInput = createdKeyDialog.getByLabel("API 密钥明文");
  await expect(plaintextInput).toHaveValue(/^mli_/);
  await createdKeyDialog.getByRole("button", { name: "关闭已创建密钥" }).click();
  await expect(createdKeyDialog).toBeHidden();
  await expect(page.getByLabel("API 密钥明文")).toHaveCount(0);

  const progressingReleaseRow = operationsDrawer.getByRole("row").filter({ hasText: "进行中" });
  await progressingReleaseRow.getByRole("button", { name: /^暂停 发布 / }).click();
  await page.getByRole("button", { name: "确认暂停" }).click();
  const pausedReleaseRow = operationsDrawer.getByRole("row").filter({ hasText: "已暂停" });
  await expect(pausedReleaseRow).toBeVisible();
  await pausedReleaseRow.getByRole("button", { name: /^恢复 发布 / }).click();
  await page.getByRole("button", { name: "确认恢复" }).click();
  await expect(operationsDrawer.getByRole("row").filter({ hasText: "进行中" })).toBeVisible();

  const completed = runInferenceFixture<RolloutFixtureResult>(
    "advance_inference_rollout.py",
    rollout.id,
    "complete",
  );
  expect(completed).toMatchObject({ state: "completed", current_step: 10000 });
  await operationsDrawer.getByRole("button", { name: "Close" }).click();
  operationsDrawer = await openOperations();
  await expect(operationsDrawer.getByRole("row").filter({ hasText: "已完成" })).toContainText("100%");
  await operationsDrawer.getByRole("button", { name: "Close" }).click();

  await deploymentRow.getByRole("button", { name: `在线测试 ${deploymentName}` }).click();
  const onlineTest = page.getByRole("dialog", { name: `在线测试: ${deploymentName}` });
  await onlineTest.getByLabel("JSON records").fill('[{"current":0,"voltage":0},{"current":9,"voltage":9}]');
  await onlineTest.getByRole("button", { name: "推理" }).click();
  await expect(onlineTest.getByText("v2", { exact: true })).toBeVisible();
  await onlineTest.getByRole("button", { name: "Close" }).click();

  operationsDrawer = await openOperations();
  const completedReleaseRow = operationsDrawer.getByRole("row").filter({ hasText: "已完成" });
  await completedReleaseRow.getByRole("button", { name: /^回滚 发布 / }).click();
  await page.getByRole("button", { name: "确认回滚" }).click();
  await expect(operationsDrawer.getByRole("row").filter({ hasText: "已回滚" })).toBeVisible();
  await operationsDrawer.getByRole("button", { name: "Close" }).click();

  await deploymentRow.getByRole("button", { name: `在线测试 ${deploymentName}` }).click();
  const rollbackPrediction = page.getByRole("dialog", { name: `在线测试: ${deploymentName}` });
  await rollbackPrediction.getByLabel("JSON records").fill('[{"current":0,"voltage":0}]');
  await rollbackPrediction.getByRole("button", { name: "推理" }).click();
  await expect(rollbackPrediction.getByText("v1", { exact: true })).toBeVisible();
  await rollbackPrediction.getByRole("button", { name: "Close" }).click();

  const applicationOrigin = new URL(page.url()).origin;
  const viewerContext = await browser.newContext();
  try {
    const viewerPage = await viewerContext.newPage();
    await viewerPage.goto(`${applicationOrigin}/login`);
    await viewerPage.getByPlaceholder("用户名").fill(viewer.username);
    await viewerPage.getByPlaceholder("密码").fill(viewer.password);
    await viewerPage.locator('button[type="submit"]').click();
    await expect(viewerPage).toHaveURL(/\/$/);
    await viewerPage.goto(`${applicationOrigin}/models`);
    await viewerPage.getByRole("combobox", { name: "项目" }).click();
    await viewerPage.getByText(new RegExp(projectName)).click();
    await viewerPage.getByRole("tab", { name: "推理部署" }).click();
    const viewerDeploymentRow = viewerPage.getByRole("row", { name: new RegExp(deploymentName) });
    await expect(viewerDeploymentRow).toBeVisible();
    await expect(viewerDeploymentRow.getByRole("button", { name: `启动 ${deploymentName}` })).toHaveCount(0);
    await expect(viewerDeploymentRow.getByRole("button", { name: `停止 ${deploymentName}` })).toHaveCount(0);
    await viewerDeploymentRow.getByRole("button", { name: `发布运维 ${deploymentName}` }).click();
    const viewerOperations = viewerPage.getByRole("dialog", { name: `发布运维: ${deploymentName}` });
    await expect(viewerOperations).toBeVisible();
    await expect(viewerOperations.getByRole("button", { name: "新建发布" })).toHaveCount(0);
    await expect(viewerOperations.getByRole("button", { name: "创建 API 密钥" })).toHaveCount(0);
    await expect(viewerOperations.getByRole("button", { name: /^回滚 发布 / })).toHaveCount(0);
  } finally {
    await viewerContext.close();
  }
});
