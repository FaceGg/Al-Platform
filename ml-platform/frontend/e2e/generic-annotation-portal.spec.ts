import { expect, test } from "@playwright/test";

test("forwards the complete sample filter contract and resets its cursor", async ({ page }) => {
  const sampleQueries: URLSearchParams[] = [];
  // App 在挂载与登录后都会探测 /portal/auth/me：登录前必须 401（否则跳过登录页），
  // 登录后返回身份。缺少该分支会让路由 mock 抛 Unexpected request，登录流程卡死。
  let loggedIn = false;
  const task = {
    id: "task-filter", assignment_id: "assignment-filter", title: "Filter review",
    status: "awaiting_annotation", task_revision: 3, scope_hash: "scope-filter", read_only: false,
    label_schema: { columns: [{ machine_key: "label", display_name: "Label", value_type: "string", required: true }] },
  };
  await page.route((url) => url.pathname.startsWith("/portal/"), async (route) => {
    const url = new URL(route.request().url());
    let body: unknown;
    if (url.pathname === "/portal/auth/me") {
      if (!loggedIn) {
        await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "PORTAL_SESSION_REQUIRED" }) });
        return;
      }
      body = { subject_id: "subject-filter", username: "annotator-filter" };
    } else if (url.pathname === "/portal/auth/login") {
      loggedIn = true;
      body = { username: "annotator-filter" };
    } else if (url.pathname === "/portal/tasks") body = { items: [task], total: 1, next_cursor: null };
    else if (url.pathname === "/portal/tasks/task-filter") body = task;
    else if (url.pathname === "/portal/notifications") body = { items: [], total: 0, unread_count: 0, next_cursor: null };
    else if (url.pathname === "/portal/comments") body = { items: [], total: 0, next_cursor: null };
    else if (url.pathname === "/portal/tasks/task-filter/samples") {
      sampleQueries.push(url.searchParams);
      body = { items: [{ sample_id: "sample-filter", values: { feature: 1 }, labels: {}, revision: 0 }], total: 1, next_cursor: null };
    } else throw new Error(`Unexpected request ${url.pathname}`);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("http://127.0.0.1:5174");
  await page.getByLabel("用户名").fill("annotator-filter");
  await page.getByLabel("密码").fill("valid-pass-8");
  await page.getByRole("button", { name: "登录" }).click();
  await page.getByRole("button", { name: "继续标注" }).click();
  // 工作区左侧为 tab 面板（默认仅展开「指南」），筛选控件在「样本」tab 内。
  await page.getByRole("tab", { name: "样本" }).click();
  await page.getByLabel("标签完成状态").selectOption("incomplete");
  await page.getByLabel("批注状态筛选").selectOption("open");
  await page.getByLabel("搜索样本").fill("sample-filter");
  await page.getByLabel("最近修改时间").selectOption({ label: "最近 24 小时" });
  await expect.poll(() => sampleQueries.some(query => query.get("modified_after"))).toBe(true);
  const last = sampleQueries.find(query => query.get("modified_after"))!;
  expect(last.get("label_status")).toBe("incomplete");
  expect(last.get("comment_status")).toBe("open");
  expect(last.get("sample_search")).toBe("sample-filter");
  expect(last.get("modified_after")).toBeTruthy();
  expect(last.get("cursor")).toBeNull();
});

test("opens the exact assigned workspace from a return notification", async ({ page }) => {
  let openedAssignment = "";
  let loggedIn = false;
  const task = {
    id: "task-notice", assignment_id: "assignment-notice", title: "Return review",
    status: "in_progress", task_revision: 4, scope_hash: "scope-notice", read_only: false,
    label_schema: { columns: [{ machine_key: "label", display_name: "Label", value_type: "string", required: true }] },
  };
  await page.route((url) => url.pathname.startsWith("/portal/"), async (route) => {
    const url = new URL(route.request().url());
    let body: unknown;
    if (url.pathname === "/portal/auth/me") {
      if (!loggedIn) {
        await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "PORTAL_SESSION_REQUIRED" }) });
        return;
      }
      body = { subject_id: "subject-notice", username: "annotator-notice" };
    } else if (url.pathname === "/portal/auth/login") {
      loggedIn = true;
      body = { username: "annotator-notice" };
    } else if (url.pathname === "/portal/tasks") body = { items: [], total: 0, next_cursor: null };
    else if (url.pathname === "/portal/notifications") body = {
      items: [{ id: "notice-return", title: "回传已退回修改", body: "请重新编辑回传。",
        event_type: "annotation_return.returned_for_changes", severity: "info",
        created_at: "2026-09-16T08:00:00", read_at: null,
        target: { task_id: "task-notice", assignment_id: "assignment-notice" } }],
      total: 1, unread_count: 1, next_cursor: null,
    };
    else if (url.pathname === "/portal/notifications/notice-return/read") body = { id: "notice-return", read_at: "2026-09-16T09:00:00" };
    else if (url.pathname === "/portal/tasks/task-notice") {
      openedAssignment = url.searchParams.get("assignment_id") ?? "";
      body = task;
    } else if (url.pathname === "/portal/tasks/task-notice/samples") {
      expect(url.searchParams.get("assignment_id")).toBe("assignment-notice");
      body = { items: [{ sample_id: "sample-notice", values: { feature: 1 }, labels: { label: "needs-edit" }, revision: 2 }], total: 1, next_cursor: null };
    } else if (url.pathname === "/portal/comments") body = { items: [], total: 0, next_cursor: null };
    else throw new Error(`Unexpected request ${route.request().method()} ${url.pathname}`);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("http://127.0.0.1:5174");
  await page.getByLabel("用户名").fill("annotator-notice");
  await page.getByLabel("密码").fill("valid-pass-8");
  await page.getByRole("button", { name: "登录" }).click();
  await page.getByRole("button", { name: "站内通知（1 条未读）" }).click();
  await page.getByRole("button", { name: "打开任务" }).click();
  await expect(page.getByText("Return review")).toBeVisible();
  await expect.poll(() => openedAssignment).toBe("assignment-notice");
  await expect(page.getByLabel("label-sample-notice")).toHaveValue("needs-edit");
});

test("refreshes portal comment resolution without overwriting label or reply drafts", async ({ page }) => {
  let resolved = false;
  let commentReads = 0;
  let notificationRead = false;
  let loggedIn = false;
  const task = {
    id: "task-refresh", assignment_id: "assignment-refresh", title: "Comment review",
    status: "awaiting_annotation", task_revision: 3, scope_hash: "scope-refresh", read_only: false,
    label_schema: { columns: [{ machine_key: "label", display_name: "Label", value_type: "string", required: true }] },
  };
  await page.route((url) => url.pathname.startsWith("/portal/"), async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/portal/auth/me") {
      if (!loggedIn) {
        await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "PORTAL_SESSION_REQUIRED" }) });
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ subject_id: "subject-refresh", username: "annotator-refresh" }) });
      return;
    }
    let body: unknown;
    switch (url.pathname) {
      case "/portal/auth/login":
        loggedIn = true;
        body = { username: "annotator-refresh" };
        break;
      case "/portal/tasks": body = { items: [task], total: 1, next_cursor: null }; break;
      case "/portal/tasks/task-refresh": body = task; break;
      case "/portal/notifications":
        body = {
          items: [{ id: "notice-1", title: "Comment updated", body: "The comment was reviewed.",
            event_type: "annotation_comment.status_changed", severity: "info", created_at: "2026-09-16T08:00:00",
            read_at: notificationRead ? "2026-09-16T09:00:00" : null }],
          total: 1, unread_count: notificationRead ? 0 : 1, next_cursor: null,
        };
        break;
      case "/portal/notifications/notice-1/read":
        notificationRead = true;
        body = { id: "notice-1", read_at: "2026-09-16T09:00:00" };
        break;
      case "/portal/tasks/task-refresh/samples":
        body = { items: [{ sample_id: "sample-1", values: { feature: 1 }, labels: { label: "original" }, revision: 0 }] };
        break;
      case "/portal/comments":
        expect(url.searchParams.get("assignment_id")).toBe("assignment-refresh");
        commentReads += 1;
        body = { items: [{ id: "comment-refresh", content: "Review this sample", sample_id: "sample-1", status: resolved ? "resolved" : "open" }], next_cursor: null };
        break;
      default: throw new Error(`Unexpected portal request: ${route.request().method()} ${url.pathname}`);
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.clock.install();
  await page.goto("http://127.0.0.1:5174");
  await page.getByLabel("用户名").fill("annotator-refresh");
  await page.getByLabel("密码").fill("valid-pass-8");
  await page.getByRole("button", { name: "登录" }).click();
  await page.getByRole("button", { name: "继续标注" }).click();
  // 批注内容、回复与新增批注输入都在「批注」tab 面板内（默认折叠）。
  await page.getByRole("tab", { name: "批注" }).click();
  await expect(page.getByText("Review this sample")).toBeVisible();
  await page.getByLabel("label-sample-1").fill("");
  await page.getByRole("button", { name: "回复", exact: true }).click();
  await page.getByLabel("新增批注").fill("Unfinished reply");
  resolved = true;
  await page.clock.fastForward(30_000);
  await expect(page.getByText("样本 sample-1 · 已解决")).toBeVisible();
  await expect(page.getByLabel("label-sample-1")).toHaveValue("");
  await expect(page.getByLabel("新增批注")).toHaveValue("Unfinished reply");
  await expect(page.getByRole("button", { name: "取消回复" })).toBeVisible();
  expect(commentReads).toBeGreaterThanOrEqual(2);
  await page.getByRole("button", { name: "站内通知（1 条未读）" }).click();
  await expect(page.getByText("The comment was reviewed.")).toBeVisible();
  await page.getByRole("button", { name: "标记已读" }).click();
  await expect(page.getByRole("button", { name: "站内通知（0 条未读）" })).toBeVisible();
  expect(notificationRead).toBe(true);
  await expect(page.getByLabel("新增批注")).toHaveValue("Unfinished reply");
  await expect(page.getByLabel("label-sample-1")).toHaveValue("");
});

test("keeps portal identity independent and enforces save, conflict, and return-lock flow", async ({ page }) => {
  let labelWrites = 0;
  let returns = 0;
  let loggedIn = false;
  // 该测试用 glob 逐路径 mock，未覆盖的 /portal/auth/me 会打到真实 dev server；
  // 显式补上会话探测分支，登录前 401、登录后返回标注员身份。
  await page.route("**/portal/auth/me", async (route) => {
    if (!loggedIn) {
      await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "PORTAL_SESSION_REQUIRED" }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ subject_id: "subject-a", username: "annotator-a" }) });
  });
  await page.route("**/portal/auth/login", async (route) => {
    loggedIn = true;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ username: "annotator-a" }) });
  });
  // 队列页请求带查询串（?limit=50&sort=due_at...），glob 必须以 ** 结尾才能命中；
  // 更具体的 task-1 路由后注册、优先匹配，不会被该通配吞掉。
  // 顶栏还会轮询 /portal/notifications，不 mock 会经 vite 代理打到不存在的后端（502）。
  await page.route("**/portal/tasks**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      items: [{ id: "task-1", title: "Review batch", status: "awaiting_annotation", task_revision: 3, scope_hash: "sha256:scope", read_only: false,
        label_schema: { columns: [{ machine_key: "label", display_name: "Label", value_type: "string", required: true }] } }],
    }) });
  });
  await page.route("**/portal/notifications**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], total: 0, unread_count: 0, next_cursor: null }) });
  });
  // 工作区会轮询任务批注，不 mock 会经 vite 代理打到不存在的后端。
  await page.route("**/portal/comments**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], next_cursor: null }) });
  });
  await page.route("**/portal/tasks/task-1**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      id: "task-1", title: "Review batch", status: "awaiting_annotation", task_revision: 3, scope_hash: "sha256:scope", read_only: false,
      label_schema: { columns: [{ machine_key: "label", display_name: "Label", value_type: "string", required: true }] },
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
  await page.getByRole("button", { name: "继续标注" }).click();
  await page.getByLabel("label-sample-1").fill("approved");
  await page.getByRole("button", { name: "保存标签" }).click();
  await expect(page.getByText("标签已保存", { exact: true })).toBeVisible();
  // 确认任务/发起回传/编辑后回传都在「回传」tab 面板内（默认折叠）。
  await page.getByRole("tab", { name: "回传" }).click();
  await page.getByRole("button", { name: "确认任务" }).click();
  await page.getByRole("button", { name: "发起回传" }).click();
  await expect(page.getByText("回传后只读")).toBeVisible();
  await expect(page.getByRole("button", { name: "编辑后回传" })).toBeVisible();
  await expect.poll(() => returns).toBe(1);
});
