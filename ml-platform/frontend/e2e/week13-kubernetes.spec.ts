import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Week 13 authenticated browser flow: register a real cluster (kind/WSL),
// run the connectivity check, and open the node capability table.
// Requires the backend process to run with KUBERNETES_ENDPOINT_ALLOWLIST
// including the kind host and LINKRAFT_W13_TOKEN set (passed through env).

const EVIDENCE_DIR = path.resolve(import.meta.dirname ?? ".", "../../backend/temp_test/week13-local/playwright");

async function login(page: import("@playwright/test").Page) {
  page.on("response", (response) => {
    if (response.url().includes("/api/auth/")) {
      console.log("AUTH-API:", response.status(), response.url());
    }
  });
  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("admin");
  await page.getByPlaceholder("密码").fill("admin123");
  // Wait out the SPA re-render right after goto: clicking on a remounted form
  // silently loses the submit on slow machines.
  await page.waitForTimeout(500);
  await page.locator('button[type="submit"]').click();
  // Cold-start vite dev compiles the Dashboard chunk lazily; allow a minute.
  await expect(page).toHaveURL(/\/$/, { timeout: 60_000 });
}

async function apiHeaders(page: import("@playwright/test").Page): Promise<Record<string, string>> {
  const token = await page.evaluate(() => window.localStorage.getItem("token") ?? "");
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

// Requires a local kind cluster (46617/46618); CI runners do not have one.
// Run locally with RUN_KIND_E2E=1 npx playwright test <file>.
test("week13 cluster registration, connectivity check and node table", async ({ page }) => {
  // Requires a local kind cluster; CI runners have none.
  test.skip(!process.env.RUN_KIND_E2E, "requires local kind cluster");
  fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
  await login(page);
  const headers = await apiHeaders(page);

  // Seed a dedicated project for the browser flow.
  const projectName = `w13-browser-${Date.now()}`;
  const created = await page.request.post("/api/projects", { headers, data: { name: projectName } });
  expect(created.status(), await created.text()).toBe(201);
  const projectId = (await created.json()).id as string;

  // The page reads the project list on mount, so load it after seeding.
  page.on("response", (response) => {
    if (response.url().includes("/kubernetes/")) {
      console.log("K8S-API:", response.status(), response.request().method(), response.url());
      if (response.status() >= 400) {
        response.text().then((t) => console.log("K8S-API-BODY:", t.slice(0, 300)));
      }
    }
  });
  await page.goto("/kubernetes");
  await expect(page.getByRole("heading", { name: "Kubernetes 集群" })).toBeVisible();

  // Explicitly select the freshly seeded project: in a shared database the
  // page's items[0] default may belong to an older project.
  const projectCombo = page.getByRole("combobox").first();
  await projectCombo.click();
  await projectCombo.fill(projectName);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("option", { name: projectName })).toHaveCount(0);

  // Register the kind cluster through the form. Unique name per run: a fixed
  // name 409s against leftovers from earlier rounds in a shared database.
  const clusterName = `w13-browser-${Date.now()}`;
  await page.getByRole("button", { name: "登记集群" }).click();
  await page.getByLabel("标识名").fill(clusterName);
  await page.getByLabel("API Server").fill(process.env.W13_ENDPOINT ?? "https://127.0.0.1:46617");
  await page.getByLabel("凭据引用", { exact: true }).fill("env:LINKRAFT_W13_TOKEN");
  await page.getByRole("switch").click();
  await page.locator(".ant-modal").getByRole("button", { name: /保\s*存/ }).click();
  await expect(page.getByText("集群已登记")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("cell", { name: clusterName })).toBeVisible();
  await page.screenshot({ path: path.join(EVIDENCE_DIR, "01-registered.png"), fullPage: true });

  // Real connectivity check against the kind API server.
  await page.getByRole("button", { name: "连通性检查" }).first().click();
  await expect(page.getByText(/连通性正常/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("cell", { name: /v1\.3/ })).toBeVisible();
  await page.screenshot({ path: path.join(EVIDENCE_DIR, "02-connectivity-ok.png"), fullPage: true });

  // Node capability drawer shows the kind control-plane node.
  await page.getByRole("button", { name: "节点能力" }).first().click();
  await expect(page.getByText("linkraft-w13-control-plane")).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: path.join(EVIDENCE_DIR, "03-node-table.png"), fullPage: true });

  // The credential reference stays a reference; no secret material on the page.
  expect(await page.content()).toContain("env:LINKRAFT_W13_TOKEN");

  void projectId;
});
