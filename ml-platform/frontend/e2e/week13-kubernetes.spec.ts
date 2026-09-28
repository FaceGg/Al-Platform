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
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/$/);
}

async function apiHeaders(page: import("@playwright/test").Page): Promise<Record<string, string>> {
  const token = await page.evaluate(() => window.localStorage.getItem("token") ?? "");
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

test("week13 cluster registration, connectivity check and node table", async ({ page }) => {
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

  // Register the kind cluster through the form.
  await page.getByRole("button", { name: "登记集群" }).click();
  await page.getByLabel("标识名").fill("w13-browser");
  await page.getByLabel("API Server").fill(process.env.W13_ENDPOINT ?? "https://127.0.0.1:46617");
  await page.getByLabel("凭据引用", { exact: true }).fill("env:LINKRAFT_W13_TOKEN");
  await page.getByRole("switch").click();
  await page.locator(".ant-modal").getByRole("button", { name: /保\s*存/ }).click();
  await expect(page.getByText("集群已登记")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("cell", { name: "w13-browser" })).toBeVisible();
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
