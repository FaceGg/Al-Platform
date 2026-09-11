import { expect, test } from "@playwright/test";

test("keeps portal identity independent and enforces save, conflict, and return-lock flow", async ({ page }) => {
  let labelWrites = 0;
  let returns = 0;
  await page.route("**/portal/auth/login", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ username: "annotator-a" }) });
  });
  await page.route("**/portal/tasks", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      items: [{ id: "task-1", title: "Review batch", status: "awaiting_annotation", task_revision: 3, scope_hash: "sha256:scope", read_only: false }],
    }) });
  });
  await page.route("**/portal/tasks/task-1", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      id: "task-1", title: "Review batch", status: "awaiting_annotation", task_revision: 3, scope_hash: "sha256:scope", read_only: false,
    }) });
  });
  await page.route("**/portal/tasks/task-1/samples**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      items: [{ sample_id: "sample-1", values: { feature: 1 }, labels: { label: "pending" }, revision: 0 }],
    }) });
  });
  await page.route("**/portal/tasks/task-1/samples/sample-1/labels", async (route) => {
    labelWrites += 1;
    if (labelWrites === 1) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ revision: 1 }) });
      return;
    }
    await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({
      detail: { code: "REVISION_CONFLICT", current_revision: 2, current_values: { label: "server-value" } },
    }) });
  });
  await page.route("**/portal/tasks/task-1/confirm", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "confirmed" }) });
  });
  await page.route("**/portal/tasks/task-1/return", async (route) => {
    returns += 1;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "pending" }) });
  });
  await page.route("**/portal/tasks/task-1/edit-for-return", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "edit_for_return" }) });
  });

  await page.goto("http://127.0.0.1:5174");
  await page.getByLabel("用户名").fill("annotator-a");
  await page.getByLabel("密码").fill("valid-pass-8");
  await page.getByRole("button", { name: "登录" }).click();
  await page.getByRole("button", { name: "打开工作区" }).click();
  await page.getByLabel("label-sample-1").fill("approved");
  await page.getByRole("button", { name: "保存标签" }).click();
  await expect(page.getByText("标签已保存")).toBeVisible();
  await page.getByRole("button", { name: "确认任务" }).click();
  await page.getByRole("button", { name: "发起回传" }).click();
  await expect(page.getByText("回传后只读")).toBeVisible();
  await expect(page.getByRole("button", { name: "编辑后回传" })).toBeVisible();
  await expect.poll(() => returns).toBe(1);
});
