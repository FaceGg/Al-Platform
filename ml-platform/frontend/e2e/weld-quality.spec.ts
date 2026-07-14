import { expect, test } from "@playwright/test";
import path from "node:path";

test("runs the welding quality template from an uploaded artifact", async ({ page }) => {
  const projectName = `E2E welding ${Date.now()}`;
  const fixture = path.resolve(import.meta.dirname, "fixtures/weld_fault_features.csv");

  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("admin");
  await page.getByPlaceholder("密码").fill("admin123");
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/$/);

  await page.goto("/projects");
  await page.getByRole("button", { name: /新建项目/ }).click();
  const projectDialog = page.getByRole("dialog");
  await projectDialog.getByLabel("项目名称").fill(projectName);
  await projectDialog.getByRole("button", { name: "OK" }).click();
  await page.getByRole("link", { name: projectName }).click();
  const projectId = new URL(page.url()).pathname.split("/").pop() || "";
  expect(projectId).not.toBe("");

  await page.goto("/data");
  await page.getByRole("combobox").click();
  await page.getByText(projectName, { exact: true }).click();
  const uploadResponse = page.waitForResponse((response) =>
    response.url().includes(`/api/projects/${projectId}/datasets/upload`) && response.status() === 200,
  );
  await page.locator('input[type="file"]').first().setInputFiles(fixture);
  await uploadResponse;

  await page.goto(`/template/weld_quality?project=${projectId}`);
  await expect(page.getByRole("heading", { level: 3 })).toContainText("焊接质量预测");
  await page.getByLabel("数据集制品").click();
  await page.getByText(/weld_fault_features.csv/).click();
  await page.getByRole("button", { name: "创建工作流" }).click();
  await expect(page).toHaveURL(/\/workspace\//);

  const runResponsePromise = page.waitForResponse((response) =>
    /\/api\/workflows\/[^/]+\/run$/.test(response.url()) && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /运行/ }).click();
  const runResponse = await runResponsePromise;
  const { run_id: runId } = await runResponse.json();

  await expect(page.getByTestId("execution-progress")).toHaveAttribute("data-status", "completed", { timeout: 90_000 });
  await expect.poll(async () => page.evaluate(async (id) => {
    const token = localStorage.getItem("token") || "";
    const response = await fetch(`/api/runs/${id}`, { headers: { Authorization: `Bearer ${token}` } });
    return response.json();
  }, runId), { timeout: 90_000 }).toMatchObject({ status: "completed" });

  const detail = await page.evaluate(async (id) => {
    const token = localStorage.getItem("token") || "";
    const response = await fetch(`/api/runs/${id}`, { headers: { Authorization: `Bearer ${token}` } });
    return response.json();
  }, runId);
  expect(detail.node_runs.some((node: { result?: { metrics?: unknown } }) => node.result?.metrics)).toBeTruthy();
});
