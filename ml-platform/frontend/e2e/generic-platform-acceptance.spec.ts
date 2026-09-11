import { expect, test } from "@playwright/test";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("admin");
  await page.getByPlaceholder("密码").fill("admin123");
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/$/);
}

test("accepts the generic annotation task workflow in the browser", async ({ page }) => {
  await login(page);

  let taskStatus = "draft";
  let previewStatus = "queued";
  const transitionActions: string[] = [];

  await page.route("**/api/projects", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [{ id: "project-1", name: "Generic project" }] }),
    });
  });
  await page.route("**/api/annotation-tasks**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/annotation-tasks") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [{
            id: "task-1",
            project_id: "project-1",
            mode: "automatic",
            status: taskStatus,
            task_revision: transitionActions.length,
            sample_scope: { kind: "ids", sample_ids: ["sample-1"] },
            task_snapshot: { config_hash: "sha256:generic-task" },
          }],
          total: 1,
          next_cursor: null,
        }),
      });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/annotation-tasks/task-1/preview") {
      previewStatus = "completed";
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          operation_id: "operation-preview-1",
          preview_id: "preview-1",
          task_revision: 0,
          status: "queued",
        }),
      });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/annotation-tasks/task-1/transition") {
      const payload = request.postDataJSON() as { action: string };
      transitionActions.push(payload.action);
      taskStatus = payload.action === "execute"
        ? "awaiting_return"
        : payload.action === "return"
          ? "returned_pending_acceptance"
          : "accepted";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "task-1",
          project_id: "project-1",
          mode: "automatic",
          status: taskStatus,
          task_revision: transitionActions.length,
        }),
      });
      return;
    }
    await route.fallback();
  });
  await page.route("**/api/annotation-tasks/task-1/previews/preview-1", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "preview-1",
        operation_id: "operation-preview-1",
        task_revision: 0,
        status: previewStatus,
        progress: previewStatus === "completed" ? 100 : 0,
        summary: { sample_count: 1 },
      }),
    });
  });
  await page.route("**/api/annotation-tasks/task-1/previews/preview-1/samples**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ id: "preview-sample-1", sample_id: "sample-1", row_index: 0, values: { feature: 1 } }],
        total: 1,
        next_cursor: null,
      }),
    });
  });
  await page.route("**/api/annotation-operations**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0, next_cursor: null }),
    });
  });

  await page.goto("/data-annotation?view=tasks&projectId=project-1");
  await expect(page.getByText("task-1")).toBeVisible();
  await expect(page.getByText("点焊标注任务")).not.toBeVisible();
  await expect(page.getByText("SPOT WELD / TASKS")).not.toBeVisible();

  const list = page.getByRole("region", { name: "通用任务列表" });
  await expect(list.getByRole("button", { name: "执行" })).toBeDisabled();
  await list.getByRole("button", { name: "预览" }).click();
  await expect(list.getByRole("button", { name: "执行" })).toBeEnabled();
  await list.getByRole("button", { name: "执行" }).click();
  await expect.poll(() => transitionActions).toContain("execute");

  await expect(list.getByRole("button", { name: "提交回传" })).toBeVisible();
  await list.getByRole("button", { name: "提交回传" }).click();
  await expect.poll(() => transitionActions).toContain("return");
  await expect(list.getByRole("button", { name: "验收" })).toBeVisible();
  await list.getByRole("button", { name: "验收" }).click();
  await expect.poll(() => transitionActions).toContain("accept");
});
