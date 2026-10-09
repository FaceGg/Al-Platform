import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Week 15 authenticated browser flow: register a catalog image, start a
// Notebook session against the real kind cluster, open it through the
// platform proxy, then stop it. The backend process must run with
// KUBERNETES_ENDPOINT_ALLOWLIST incl. 127.0.0.1 and the kind SA token env.

const EVIDENCE_DIR = path.resolve(import.meta.dirname ?? ".", "../../backend/temp_test/week15-local/playwright");

const DIGEST = "sha256:8c903974902b0e9d45d9823c2234411de0614c5c98c4bb782b3d4f55b3e435e6";
const IMAGE_REF = `docker.io/jupyter/base-notebook@${DIGEST}`;

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("admin");
  await page.getByPlaceholder("密码").fill("admin123");
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/$/);
}

async function apiHeaders(page: import("@playwright/test").Page): Promise<Record<string, string>> {
  const token = await page.evaluate(() => window.localStorage.getItem("token") ?? "");
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

test("week15 image register and notebook lifecycle", async ({ page }) => {
  fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
  await login(page);
  const headers = await apiHeaders(page);

  // Seed: project + active cluster + namespace (API), like the smoke script.
  const stamp = Date.now();
  const created = await page.request.post("/api/projects", {
    headers,
    data: { name: `w15-browser-${stamp}` },
  });
  expect(created.status(), await created.text()).toBe(201);
  const projectId = (await created.json()).id as string;
  const registered = await page.request.post("/api/kubernetes/clusters", {
    headers,
    data: {
      project_id: projectId,
      name: `w15-browser-${stamp}`,
      display_name: "Week 15 browser",
      api_server_url: process.env.W14_ENDPOINT ?? "https://127.0.0.1:46617",
      secret_ref: "env:LINKRAFT_W14_TOKEN",
      provider: "kind",
      insecure_tls: true,
    },
  });
  expect(registered.status(), await registered.text()).toBe(201);
  const clusterId = (await registered.json()).id as string;
  const check = await page.request.post(`/api/kubernetes/clusters/${clusterId}/connectivity-check`, { headers });
  expect((await check.json()).check_status).toBe("ok");
  const ensured = await page.request.put(`/api/kubernetes/clusters/${clusterId}/namespaces/w14-demo`, {
    headers,
    data: { quota_json: { cpu_cores: 4, memory_mb: 8192 } },
  });
  expect(ensured.status(), await ensured.text()).toBe(200);

  // Page 1: ImageCatalogPage — register the jupyter baseline via the form
  // (skipped when a previous run already registered this digest: 409 would
  // keep the modal open by design).
  await page.goto("/images");
  await expect(page.getByRole("heading", { name: "镜像目录" })).toBeVisible();
  const catalog = await page.request.get("/api/images", { headers });
  const alreadyRegistered = ((await catalog.json()).items as Array<{ repository: string }>).some(
    (item) => item.repository === "jupyter/base-notebook",
  );
  if (!alreadyRegistered) {
    await page.getByRole("button", { name: "登记镜像" }).click();
    await page.getByPlaceholder("registry.local").fill("docker.io");
    await page.getByPlaceholder("w15/notebook-base").fill("jupyter/base-notebook");
    await page.getByPlaceholder("sha256:…").fill(DIGEST);
    // Widen visibility to platform so later runs (new projects) can use it.
    const visibilityCombo = page.locator(".ant-modal").getByRole("combobox").first();
    await visibilityCombo.click();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await page.locator(".ant-modal").getByRole("button", { name: /保\s*存/ }).click();
    await expect(page.getByText("镜像已登记")).toBeVisible({ timeout: 15_000 });
  }
  await expect(page.getByText("docker.io/jupyter/base-notebook")).toBeVisible();
  await page.screenshot({ path: path.join(EVIDENCE_DIR, "01-image-catalog.png"), fullPage: true });

  // Page 2: NotebookPage — start a session limited to catalog images.
  await page.goto("/notebooks");
  await expect(page.getByRole("heading", { name: "Notebook 会话" })).toBeVisible();
  await page.getByRole("button", { name: "启动会话" }).click();
  // antd Select: use typeahead + Enter — deterministic, no dropdown clicks.
  const clusterCombo = page.getByRole("combobox").first();
  await clusterCombo.click();
  await clusterCombo.fill(`w15-browser-${stamp}`);
  await page.keyboard.press("Enter");
  // Namespace options load async for the chosen cluster; pick the RBAC-backed one.
  const namespaceCombo = page.getByRole("combobox").nth(1);
  await namespaceCombo.click({ force: true });
  await namespaceCombo.fill("w14-demo");
  await page.keyboard.press("Enter");
  const imageCombo = page.getByRole("combobox").nth(2);
  await imageCombo.click();
  await imageCombo.fill("jupyter");
  await page.keyboard.press("Enter");
  // The OK click is dispatched directly: leftover dropdown portals from the
  // typeahead eat hit-tested clicks.
  await page.locator(".ant-modal").getByRole("button", { name: /^启\s*动$/ }).dispatchEvent("click");
  // Wait for the new row (the success toast is a 3s transient).
  await expect(
    page.getByRole("row").filter({ hasText: "lr-notebook-" }).first(),
  ).toBeVisible({ timeout: 60_000 });

  // The row settles to running (poll the API like the smoke reconcile loop).
  let status = "";
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    const listed = await page.request.get("/api/notebooks", { headers });
    const items = (await listed.json()).items as Array<{ status: string }>;
    status = items[0]?.status ?? "";
    if (status === "running") break;
    await page.waitForTimeout(4000);
  }
  expect(status).toBe("running");
  await page.reload();
  const row = page.getByRole("row").filter({ hasText: "lr-notebook-" }).first();
  await expect(row.getByText("running")).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: path.join(EVIDENCE_DIR, "02-notebook-running.png"), fullPage: true });

  // Open wires through the platform proxy into a new tab; the served page is
  // the real Jupyter UI.
  const [proxyPage] = await Promise.all([
    page.waitForEvent("popup", { timeout: 30_000 }),
    row.getByRole("button", { name: "打开" }).click(),
  ]);
  await expect(proxyPage).toHaveURL(/\/proxy\//);
  await expect(proxyPage.locator("body")).toContainText(/Jupyter/i, { timeout: 30_000 });
  await proxyPage.close();
  await page.screenshot({ path: path.join(EVIDENCE_DIR, "03-notebook-open.png"), fullPage: true });

  // Stop from the UI; the row settles to stopped.
  await row.getByRole("button", { name: "停止" }).click();
  await expect(row.getByText("stopped")).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: path.join(EVIDENCE_DIR, "04-notebook-stopped.png"), fullPage: true });

  void projectId;
});
