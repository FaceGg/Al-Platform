import { expect, test } from "@playwright/test";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("admin");
  await page.getByPlaceholder("密码").fill("admin123");
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/$/);
}

test("submits a multi-output AutoML contract from the browser", async ({ page }) => {
  await login(page);

  await page.route("**/api/projects", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [{ id: "project-1", name: "Contract project" }] }),
    });
  });
  await page.route("**/api/training/automl/jobs**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/datasets?project_id=project-1", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [{ id: "dataset-1", name: "multioutput.csv" }] }),
    });
  });
  await page.route("**/api/experiments?project_id=project-1", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ id: "experiment-1", name: "Contract experiment", automl_used: false }]),
    });
  });
  await page.route("**/api/datasets/dataset-1/preview", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        columns: ["feature_a", "feature_b", "label_a", "label_b"],
        dtypes: { feature_a: "float64", feature_b: "int64", label_a: "int64", label_b: "int64" },
        preview: [],
      }),
    });
  });
  await page.route("**/api/training/automl/run", async (route) => {
    expect(route.request().method()).toBe("POST");
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({ job_id: "job-1", status: "queued", task_id: "task-1" }),
    });
  });
  await page.route("**/api/training/jobs/job-1", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: "job-1", status: "queued", metrics: {} }),
    });
  });

  await page.goto("/automl");
  await page.getByRole("button", { name: "新建" }).click();

  const modal = page.getByRole("dialog", { name: "新建通用自动建模" });
  const comboboxes = modal.getByRole("combobox");
  const openSelect = async (label: string) => {
    const input = modal.locator(`[aria-label="${label}"]`);
    const select = input.locator(
      "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' ant-select ')][1]",
    );
    await select.locator(".ant-select-selector").click();
  };
  await comboboxes.nth(0).click();
  await page.getByText("Contract project", { exact: true }).click();
  await comboboxes.nth(1).click();
  await page.getByText("multioutput.csv", { exact: true }).click();
  await expect.poll(() => page.locator(".ant-select-selection-item").count()).toBeGreaterThan(0);

  await openSelect("任务类型");
  await page.locator(".ant-select-item-option-content").filter({ hasText: "Multi-output Regression" }).click();
  await openSelect("目标列");
  await page.locator(".ant-select-item-option-content").filter({ hasText: "label_a" }).click();
  await page.locator(".ant-select-item-option-content").filter({ hasText: "label_b" }).click();

  await openSelect("输入列");
  const inputOptions = page.locator(".ant-select-dropdown:visible .ant-select-item-option-content");
  await expect(inputOptions.filter({ hasText: "label_a" })).toHaveCount(0);
  await expect(inputOptions.filter({ hasText: "label_b" })).toHaveCount(0);
  await expect(inputOptions.filter({ hasText: "feature_a" })).toHaveCount(1);
  await expect(inputOptions.filter({ hasText: "feature_b" })).toHaveCount(1);
  await page.keyboard.press("Escape");

  const requestPromise = page.waitForRequest("**/api/training/automl/run");
  await modal.getByRole("button", { name: /运行|Run/ }).click();
  const request = await requestPromise;
  const payload = request.postDataJSON() as Record<string, unknown>;
  expect(payload).toMatchObject({
    project_id: "project-1",
    experiment_id: "experiment-1",
    dataset_artifact_id: "dataset-1",
    task: "multioutput_regression",
    target_columns: ["label_a", "label_b"],
    input_columns: ["feature_a", "feature_b"],
    // 2026-09-11 合同更正后强度枚举为 light/medium/high/ultra，默认 medium（与
    // AutoMLPage.test.tsx 的单测断言一致），旧值 "balanced" 不再存在。
    search_strength: "medium",
    time_budget: 3600,
    class_weight: false,
    cross_validation_folds: 5,
  });
  expect(payload).not.toHaveProperty("target_column");
  expect(request.headers()["idempotency-key"]).toBeTruthy();
});
