import { expect, test, type Page } from "@playwright/test";

type Credentials = { username: string; password: string };
type ApiResult = { status: number; body: unknown };

const UI = {
  notifications: /(?:\u901a\u77e5|Notifications)/,
  governance: /(?:\u9879\u76ee\u6cbb\u7406|Project governance)/,
  addEndpoint: /(?:\u6dfb\u52a0\u7aef\u70b9|Add endpoint)/,
  channel: /(?:\u901a\u9053|Channel)/,
  inApp: /(?:\u7ad9\u5185\u901a\u77e5|In-app)/,
  recipients: /(?:\u63a5\u6536\u7528\u6237|Recipient users)/,
  save: /^(?:\u4fdd\s*\u5b58|Save)$/,
  testEndpoint: /(?:\u6d4b\u8bd5\u7aef\u70b9|Test endpoint)/,
  unread: /(?:\u901a\u77e5.*\u672a\u8bfb|Notifications.*unread)/,
};

async function loginAs(page: Page, credentials: Credentials, absolute = false) {
  await page.goto(absolute ? "http://127.0.0.1:5173/login" : "/login");
  await page.getByPlaceholder(/(?:\u7528\u6237\u540d|Username)/).fill(credentials.username);
  await page.getByPlaceholder(/(?:\u5bc6\u7801|Password)/).fill(credentials.password);
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/$/);
}

async function api(
  page: Page,
  path: string,
  method: "GET" | "POST",
  payload?: unknown,
): Promise<ApiResult> {
  return page.evaluate(async ({ path: requestPath, method: requestMethod, payload: requestPayload }) => {
    const token = localStorage.getItem("token") || "";
    const response = await fetch(requestPath, {
      method: requestMethod,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(requestPayload === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(requestPayload === undefined ? {} : { body: JSON.stringify(requestPayload) }),
    });
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    return { status: response.status, body };
  }, { path, method, payload });
}

async function register(page: Page, credentials: Credentials): Promise<ApiResult> {
  return page.evaluate(async (candidate) => {
    const response = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(candidate),
    });
    return { status: response.status, body: await response.json() };
  }, credentials);
}

async function selectOption(
  page: Page,
  dialog: ReturnType<Page["getByRole"]>,
  label: RegExp,
  option: RegExp,
) {
  const select = dialog.getByLabel(label).locator(
    "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' ant-select ')][1]",
  );
  await select.locator(".ant-select-selector").click();
  await page.locator(".ant-select-dropdown:visible").getByText(option, { exact: true }).click();
}

test("project governance and notification delivery", async ({ page, browser }) => {
  const unique = Date.now();
  const endpointName = `governance-in-app-${unique}`;
  const projectName = `Notification governance ${unique}`;
  const viewer = { username: `notification-viewer-${unique}`, password: "viewer-e2e-password" };
  const outsider = { username: `notification-outsider-${unique}`, password: "outsider-e2e-password" };
  const staticMessageWarnings: string[] = [];
  page.on("console", (entry) => {
    if (
      entry.type() === "error"
      && entry.text().includes("Static function can not consume context")
    ) {
      staticMessageWarnings.push(entry.text());
    }
  });

  await loginAs(page, { username: "admin", password: "admin123" });
  expect((await register(page, viewer)).status).toBe(200);
  expect((await register(page, outsider)).status).toBe(200);

  const project = await api(page, "/api/projects", "POST", {
    name: projectName,
    description: "Chromium notification governance acceptance",
  });
  expect(project.status).toBe(201);
  const projectId = String((project.body as { id: string }).id);
  expect(projectId).not.toBe("");

  const membership = await api(page, `/api/projects/${projectId}/members`, "POST", {
    username: viewer.username,
    role: "viewer",
  });
  expect(membership.status).toBe(201);

  await page.goto(`/projects/${projectId}`);
  const governance = page.getByLabel(UI.governance);
  await governance.getByRole("tab", { name: UI.notifications }).click();
  await governance.getByRole("button", { name: UI.addEndpoint }).click();

  const endpointDialog = page.getByRole("dialog", { name: UI.addEndpoint });
  await selectOption(page, endpointDialog, UI.channel, UI.inApp);
  await selectOption(page, endpointDialog, UI.recipients, /admin/);
  await endpointDialog.getByLabel(/(?:\u7aef\u70b9\u540d\u79f0|Endpoint name)/).fill(endpointName);

  const createdResponsePromise = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && response.url().endsWith(`/api/projects/${projectId}/notification-endpoints`)
  ));
  await endpointDialog.getByRole("button", { name: UI.save }).click();
  const createdResponse = await createdResponsePromise;
  expect(createdResponse.status()).toBe(201);
  const created = await createdResponse.json() as Record<string, unknown>;
  expect(created).not.toHaveProperty("config");
  expect(created).not.toHaveProperty("encrypted_config");
  expect(JSON.stringify(created)).not.toContain("recipient_user_ids");

  const endpointRow = governance.getByRole("row", { name: new RegExp(endpointName) });
  await expect(endpointRow).toBeVisible();
  const deliveryResponsePromise = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && response.url().endsWith(`/api/projects/${projectId}/notification-endpoints/${created.id}/test`)
  ));
  await endpointRow.getByRole("button", { name: UI.testEndpoint }).click();
  const deliveryResponse = await deliveryResponsePromise;
  expect(deliveryResponse.status()).toBe(200);
  expect(await deliveryResponse.json()).toMatchObject({ status: "sent", error_code: null });

  await page.reload();
  const notificationButton = page.getByRole("button", { name: UI.unread });
  await expect(notificationButton).toBeVisible();
  await notificationButton.click();
  const notificationItem = page.locator(".ant-popover .ant-list-item").filter({
    hasText: new RegExp(`notification_endpoint ${created.id}`),
  });
  await expect(notificationItem).toBeVisible();
  await expect(notificationItem).toContainText(/(?:\u672a\u8bfb|Unread)/);
  expect(staticMessageWarnings).toEqual([]);

  const viewerContext = await browser.newContext();
  const outsiderContext = await browser.newContext();
  try {
    const viewerPage = await viewerContext.newPage();
    await loginAs(viewerPage, viewer, true);
    expect((await api(viewerPage, `/api/projects/${projectId}/notification-endpoints`, "GET")).status).toBe(200);
    expect((await api(viewerPage, `/api/projects/${projectId}/notification-endpoints`, "POST", {
      kind: "webhook",
      name: `viewer-denied-${unique}`,
      config: {
        url: "https://receiver.example.invalid/notification",
        headers: {},
        signature_mode: "none",
      },
    })).status).toBe(403);

    const outsiderPage = await outsiderContext.newPage();
    await loginAs(outsiderPage, outsider, true);
    expect((await api(outsiderPage, `/api/projects/${projectId}/notification-endpoints`, "GET")).status).toBe(404);
  } finally {
    await viewerContext.close();
    await outsiderContext.close();
  }
});
