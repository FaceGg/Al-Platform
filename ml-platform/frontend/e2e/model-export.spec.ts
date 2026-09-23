import { expect, test } from "@playwright/test";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("admin");
  await page.getByPlaceholder("密码").fill("admin123");
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/$/);
}

test("exports an approved model package after the async export is ready", async ({ page }) => {
  await login(page);

  let exportPolls = 0;
  let downloadRequests = 0;
  await page.route("**/api/projects", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [{ id: "project-1", name: "Generic project", project_role: "owner" }] }),
    });
  });
  await page.route("**/api/projects/project-1/registered-models", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [{ id: "model-1", project_id: "project-1", name: "Reviewed model", description: "", latest_version: 1, latest_approval_status: "approved" }] }),
    });
  });
  await page.route("**/api/registered-models/model-1/versions", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{
        id: "version-1",
        registered_model_id: "model-1",
        version_number: 1,
        source_kind: "platform_joblib",
        framework: "scikit-learn",
        algorithm: "LogisticRegression",
        feature_schema: [{ name: "feature", dtype: "float64" }],
        output_schema: { name: "label", dtype: "string", task: "classification" },
        metrics: {},
        conversion_metadata: {},
        approval_status: "approved",
        approval_comment: "",
        created_at: null,
      }]),
    });
  });
  await page.route("**/api/projects/project-1/inference-deployments", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route("**/api/projects/project-1/model-exports", async (route) => {
    expect(route.request().method()).toBe("POST");
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({ id: "export-1", status: "queued" }),
    });
  });
  await page.route("**/api/model-exports/export-1", async (route) => {
    exportPolls += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: "export-1", status: exportPolls < 2 ? "running" : "ready", checksum: "sha256:export" }),
    });
  });
  await page.route("**/api/model-exports/export-1/download", async (route) => {
    downloadRequests += 1;
    await route.fulfill({ status: 200, contentType: "application/zip", body: "signed-package" });
  });

  await page.goto("/models");
  await page.getByRole("combobox", { name: /Project|项目/ }).click();
  await page.getByText(/Generic project \((owner|所有者)\)/).click();
  await page.getByRole("button", { name: /^(Versions|版本) Reviewed model$/ }).click();
  await expect(page.getByLabel(/Reviewed model.*(Versions|版本)/).getByText(/Approved|已批准/)).toBeVisible();
  await page.getByRole("button", { name: /Export predict package 1|导出预测包 1/ }).click();

  await expect.poll(() => exportPolls).toBeGreaterThanOrEqual(2);
  await expect.poll(() => downloadRequests).toBe(1);
});
