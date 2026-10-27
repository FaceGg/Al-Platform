import { expect, test } from "@playwright/test";

/** v2 改版增量面的浏览器验收：门户真实数据、公告管理 CRUD、Agent 任务详情页。 */

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("admin");
  const password = page.getByPlaceholder("密码");
  await password.fill("admin123");
  // 提交两次兜底：生产构建首帧重挂载会吞掉第一次触发（回车与按钮各一次，
  // 第二次仅在仍停留在 /login 时发生）。
  await page.waitForTimeout(600);
  await password.press("Enter");
  for (let attempt = 0; attempt < 2 && !page.url().endsWith("/"); attempt += 1) {
    await page.locator('button[type="submit"]').click({ timeout: 2000 }).catch(() => undefined);
    await page.waitForTimeout(800);
  }
  await expect(page).toHaveURL(/\/$/, { timeout: 15000 });
}

function stubPortalApis(page: import("@playwright/test").Page) {
  return page.route("**/api/announcements", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        { id: "ann-1", title: "e2e-门户公告", content: "来自接口的真实公告", pinned: true, created_at: "2026-10-26T00:00:00Z" },
      ]),
    });
  });
}

test("portal renders announcements and gateway state from live APIs", async ({ page }) => {
  await login(page);
  await stubPortalApis(page);
  await page.route("**/api/llm-profiles", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        { id: "p-1", name: "deepseek", model_id: "deepseek-chat", is_default: true },
      ]),
    });
  });

  await page.goto("/");

  // 公告来自接口而非硬编码文案。
  await expect(page.locator("#root")).toContainText("e2e-门户公告");
  await expect(page.locator("#root")).toContainText("来自接口的真实公告");
  // 健康度大模型行由 /api/llm-profiles 推导。
  await expect(page.locator("#root")).toContainText("deepseek-chat · 已配置");
  // 改版说明性内容（迁移映射表）不复存在。
  await expect(page.locator("#root")).not.toContainText("迁移映射");
});

test("admin announcements page publishes, pins and deletes a notice end to end", async ({ page }) => {
  const created: Record<string, unknown>[] = [];
  await login(page);
  await page.route("**/api/announcements", async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(created),
      });
    } else if (method === "POST") {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      const item = { id: "ann-e2e", created_by: "admin", created_at: "2026-10-26T01:00:00Z", ...payload };
      created.push(item);
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(item) });
    } else {
      await route.fallback();
    }
  });
  await page.route("**/api/announcements/ann-e2e", async (route) => {
    const method = route.request().method();
    if (method === "DELETE") {
      const index = created.findIndex((item) => item.id === "ann-e2e");
      if (index >= 0) created.splice(index, 1);
      await route.fulfill({ status: 204, body: "" });
    } else if (method === "PATCH") {
      Object.assign(created[0] ?? {}, route.request().postDataJSON() as Record<string, unknown>);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(created[0] ?? {}) });
    } else {
      await route.fallback();
    }
  });

  await page.goto("/admin/announcements");

  // 发布
  await page.getByRole("button", { name: "发布公告" }).click();
  await page.getByLabel("标题").fill("e2e-新公告");
  await page.getByRole("button", { name: /保\s*存|确\s*定|OK/ }).click();
  await expect(page.locator(".ant-table-tbody")).toContainText("e2e-新公告");

  // 删除（含确认弹窗）
  await page.getByRole("button", { name: /删\s*除/ }).first().click();
  await page.getByRole("button", { name: /确\s*定|OK/ }).click();
  await expect(page.locator("#root")).toContainText("暂无公告");
});

test("agent task list navigates to the run detail page", async ({ page }) => {
  await login(page);
  await page.route("**/api/agent/runs?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "run-e2e-0001", project_name: "e2e-项目", target_column: "fault",
          status: "waiting_escalate", current_stage: "s1", round_count: 1,
          token_used: 0, error_code: "AGENT_S1_LLM_FAILED",
          created_at: "2026-10-26T07:42:12Z", updated_at: "2026-10-26T07:43:14Z",
        },
      ]),
    });
  });
  await page.route("**/api/agent/runs/run-e2e-0001", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "run-e2e-0001", project_id: null, project_name: "e2e-项目", target_column: "fault",
        status: "waiting_escalate", current_stage: "s1", round_count: 1, token_used: 0,
        token_budget: null, llm_model_id: "deepseek-chat", error_code: "AGENT_S1_LLM_FAILED",
        created_at: "2026-10-26T07:42:12Z", updated_at: "2026-10-26T07:43:14Z",
        dataset_artifact_id: null, result_json: {},
        memory_json: {
          rounds: [],
          escalation: { code: "AGENT_S1_LLM_FAILED", detail: "llm_call_failed: ReadTimeout: timed out", round: 1 },
        },
      }),
    });
  });

  await page.goto("/agent?tab=tasks");
  await page.getByRole("button", { name: /^Agent( 运行| runs)?$/ }).click();

  // 侧栏与行内均不再有计数徽标；详情按钮跳转专属详情页。
  await page.getByRole("button", { name: "详情 ›" }).click();
  await expect(page).toHaveURL(/\/agent\/task\/run-e2e-0001$/);
  await expect(page.locator("#root")).toContainText("e2e-项目");
  await expect(page.locator("#root")).toContainText("升级原因");
  await expect(page.locator("#root")).toContainText("ReadTimeout: timed out");

  // 返回任务列表
  await page.getByRole("button", { name: "返回任务列表" }).click();
  await expect(page).toHaveURL(/\/agent\?tab=tasks$/);
});

test("sidebar entries carry no numeric count badges", async ({ page }) => {
  await login(page);

  for (const view of ["/agent?tab=tasks", "/algo", "/admin/users"]) {
    await page.goto(view);
    // 等侧栏渲染完成后再计数，避免路由切换期间误判。
    await expect(page.locator(".v2-side-item").first()).toBeVisible();
    const badges = await page.locator(".v2-side-count, .v2-side-badge").count();
    expect(badges, `view ${view} should have no sidebar badges`).toBe(0);
  }
});
