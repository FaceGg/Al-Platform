import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Week 14 authenticated browser flow: submit a batch job against the real
// kind cluster (via the platform API), watch the JobRunsPage status flow,
// read cursor logs in the drawer, then cancel a long job from the UI.
// The backend process must run with KUBERNETES_ENDPOINT_ALLOWLIST including
// 127.0.0.1, LINKRAFT_W14_TOKEN set, and the busybox digest prefix approved
// (all inherited through the playwright webServer env).

const EVIDENCE_DIR = path.resolve(import.meta.dirname ?? ".", "../../backend/temp_test/week14-local/playwright");

const DIGEST = "sha256:fd7dc98638c8e305f4dc34e979f1c0fdfdcaeb0fbf8fcff77ae834b6da3d7e6e";
const IMAGE_REF = `docker.io/library/busybox@${DIGEST}`;
const NAMESPACE = "w14-demo";

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

async function pollJobStatus(
  page: import("@playwright/test").Page,
  headers: Record<string, string>,
  jobId: string,
  wanted: string[],
  deadlineMs = 120_000,
): Promise<string> {
  // No celery worker runs in the e2e stack: reconcile from the test, the same
  // way the beat task would in production.
  const started = Date.now();
  let ticks = 0;
  let status = "";
  while (Date.now() - started < deadlineMs) {
    ticks += 1;
    if (ticks % 3 === 0) {
      await page.request.post(`/api/kubernetes/jobs/${jobId}/reconcile`, { headers });
    }
    const res = await page.request.get(`/api/kubernetes/jobs/${jobId}`, { headers });
    status = ((await res.json()) as { status?: string }).status ?? "";
    if (wanted.includes(status)) return status;
    await page.waitForTimeout(3000);
  }
  return status;
}

test("week14 job submit, status flow, cursor logs and cancel", async ({ page }) => {
  fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
  await login(page);
  const headers = await apiHeaders(page);

  // Seed project + active cluster + registered namespace through the API.
  const stamp = Date.now();
  const created = await page.request.post("/api/projects", {
    headers,
    data: { name: `w14-browser-${stamp}` },
  });
  expect(created.status(), await created.text()).toBe(201);
  const projectId = (await created.json()).id as string;

  const registered = await page.request.post("/api/kubernetes/clusters", {
    headers,
    data: {
      project_id: projectId,
      name: `w14-browser-${stamp}`,
      display_name: "Week 14 browser flow",
      api_server_url: process.env.W14_ENDPOINT ?? "https://127.0.0.1:46617",
      secret_ref: "env:LINKRAFT_W14_TOKEN",
      provider: "kind",
      insecure_tls: true,
    },
  });
  expect(registered.status(), await registered.text()).toBe(201);
  const clusterId = (await registered.json()).id as string;

  const check = await page.request.post(`/api/kubernetes/clusters/${clusterId}/connectivity-check`, { headers });
  const checkBody = (await check.json()) as { check_status?: string; kubernetes_version?: string };
  expect(checkBody.check_status, JSON.stringify(checkBody)).toBe("ok");
  expect(checkBody.kubernetes_version).toMatch(/^v1\.3/);

  const ensured = await page.request.put(
    `/api/kubernetes/clusters/${clusterId}/namespaces/${NAMESPACE}`,
    { headers, data: { quota_json: { cpu_cores: 2, memory_mb: 2048 } } },
  );
  expect(ensured.status(), await ensured.text()).toBe(200);

  // Submit the echo job (succeeded path) and the long job (cancel path).
  const submit = async (key: string, args: string[], timeoutSeconds: number) => {
    const res = await page.request.post("/api/kubernetes/jobs", {
      headers: { ...headers, "Idempotency-Key": key },
      data: {
        cluster_id: clusterId,
        namespace: NAMESPACE,
        image_ref: IMAGE_REF,
        command: ["/bin/sh"],
        args,
        env: { W14_SMOKE: "browser" },
        resources: { cpu_cores: 1, memory_gb: 1 },
        timeout_seconds: timeoutSeconds,
      },
    });
    expect(res.status(), await res.text()).toBe(201);
    return (await res.json()) as { id: string; job_name: string };
  };
  const echoJob = await submit(`w14-browser-echo-${stamp}`, ["-c", "echo w14-browser-log-marker"], 120);
  const longJob = await submit(`w14-browser-cancel-${stamp}`, ["-c", "sleep 300"], 300);

  // Drive the JobRunsPage: list shows both deterministic job names.
  await page.goto("/kubernetes/jobs");
  await expect(page.getByRole("heading", { name: "作业运行" })).toBeVisible();
  await expect(page.getByRole("cell", { name: echoJob.job_name })).toBeVisible({ timeout: 15_000 });
  await page.screenshot({ path: path.join(EVIDENCE_DIR, "01-job-list.png"), fullPage: true });

  // Status flows to succeeded via reconcile (no celery watcher in e2e: poll API first).
  const finalStatus = await pollJobStatus(page, headers, echoJob.id, ["succeeded"]);
  expect(finalStatus).toBe("succeeded");
  await page.getByRole("button", { name: "刷新" }).click();
  const echoRow = page.getByRole("row", { name: new RegExp(echoJob.job_name) });
  await expect(echoRow.getByText("succeeded")).toBeVisible();

  // Cursor log drawer shows the pod marker and the end-of-stream marker.
  await echoRow.getByRole("button", { name: /日志/ }).click();
  await expect(page.getByText("w14-browser-log-marker")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("end-of-stream")).toBeVisible();
  await page.screenshot({ path: path.join(EVIDENCE_DIR, "02-logs.png"), fullPage: true });
  await page.keyboard.press("Escape");

  // Cancel the long job from the UI; the row settles to cancelled and the
  // cancel button becomes disabled (terminal jobs cannot be cancelled).
  const longRow = page.getByRole("row", { name: new RegExp(longJob.job_name) });
  await expect(longRow).toBeVisible();
  await longRow.getByRole("button", { name: "取消" }).click();
  await expect(page.getByText("已请求取消")).toBeVisible({ timeout: 30_000 });
  await expect(longRow.getByText("cancelled")).toBeVisible({ timeout: 30_000 });
  await expect(longRow.getByRole("button", { name: "取消" })).toBeDisabled();
  await page.screenshot({ path: path.join(EVIDENCE_DIR, "03-cancelled.png"), fullPage: true });

  void projectId;
});
