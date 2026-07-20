import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

test("model registry inference lifecycle", async ({ page }) => {
  const unique = Date.now();
  const projectName = `Inference E2E ${unique}`;

  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("admin");
  await page.getByPlaceholder("密码").fill("admin123");
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/$/);

  const seeded = await page.evaluate(async (name) => {
    const token = localStorage.getItem("token") || "";
    const response = await fetch("/api/projects", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ name, description: "Inference browser acceptance" }),
    });
    if (!response.ok) throw new Error(`Project creation failed: ${response.status}`);
    return response.json();
  }, projectName);
  const fixtureScript = path.resolve(import.meta.dirname, "fixtures/seed_inference_model.py");
  const fixture = JSON.parse(execFileSync("python", [fixtureScript, String(seeded.id)], {
    encoding: "utf-8",
    env: process.env,
  }));

  await page.goto("/models");
  await page.getByRole("combobox", { name: "项目" }).click();
  await page.getByText(new RegExp(projectName)).click();
  await page.getByRole("button", { name: "新建注册模型" }).click();
  await page.getByLabel("名称").fill(`Weld fault ${unique}`);
  await page.getByRole("dialog").getByRole("button", { name: "创建" }).click();

  const modelRow = page.getByRole("row", { name: new RegExp(`Weld fault ${unique}`) });
  await modelRow.getByRole("button", { name: new RegExp("注册版本") }).click();
  await page.getByLabel("来源训练模型 ID").fill(fixture.model_library_id);
  await page.getByRole("dialog").getByRole("button", { name: "注册版本" }).click();

  await modelRow.getByRole("button", { name: `版本 Weld fault ${unique}`, exact: true }).click();
  await page.getByRole("button", { name: "批准 版本 1" }).click();
  const versionDrawer = page.getByRole("dialog", { name: `Weld fault ${unique} 版本` });
  await expect(versionDrawer.getByText("已批准")).toBeVisible();
  await versionDrawer.getByRole("button", { name: "Close" }).click();

  await page.getByRole("tab", { name: "推理部署" }).click();
  await page.getByRole("button", { name: "新建部署" }).click();
  const deploymentDialog = page.getByRole("dialog", { name: "新建部署" });
  await deploymentDialog.locator("input#name").fill(`line-${unique}`);
  await deploymentDialog.getByRole("combobox", { name: "* 版本" }).click();
  await page.getByText(new RegExp(`Weld fault ${unique} v1`)).click();
  await deploymentDialog.getByRole("button", { name: "创建" }).click();

  const deploymentRow = page.getByRole("row", { name: new RegExp(`line-${unique}`) });
  await deploymentRow.getByRole("button", { name: new RegExp("启动") }).click();
  await expect(deploymentRow.getByText("运行中")).toHaveCount(2);
  await expect(deploymentRow.getByRole("button", { name: new RegExp("停止") })).toBeVisible();
  await deploymentRow.getByRole("button", { name: new RegExp("在线测试") }).click();
  const onlineTest = page.getByRole("dialog", { name: `在线测试: line-${unique}` });
  await onlineTest.getByLabel("JSON records").fill('[{"current":0,"voltage":0},{"current":9,"voltage":9}]');
  await onlineTest.getByRole("button", { name: "推理" }).click();
  await expect(onlineTest.getByText("v1")).toBeVisible();
  await expect(onlineTest.getByText(/0\.9/)).toBeVisible();
  await onlineTest.getByRole("button", { name: "Close" }).click();
  await deploymentRow.getByRole("button", { name: new RegExp("停止") }).click();
  await expect(deploymentRow.getByText("已停止")).toHaveCount(2);
});
