import { expect, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { resolveE2ePython } from "./pythonExecutable";

type Credentials = { username: string; password: string };
type ApiMethod = "GET" | "POST" | "PATCH" | "DELETE";
type ApiResult = {
  status: number;
  body: unknown;
  retryAfter: string | null;
};
type SeededInferenceSources = { model_library_ids: string[] };
type RolloutFixtureResult = {
  state: string;
  current_step: number;
  lock_version: number;
};

type Week12AcceptanceConfig = {
  baseUrl?: string;
  isolationConfirmed: boolean;
  ownerUsername?: string;
  ownerPassword?: string;
  fixtureDatabaseUrl?: string;
  inferenceRuntimeUrl?: string;
  inferenceInternalSecret?: string;
  mailpitApiUrl?: string;
  webhookReceiverUrl?: string;
  webhookReceiverEventsUrl?: string;
  webhookSigningSecret?: string;
  wecomReceiverUrl?: string;
  wecomReceiverEventsUrl?: string;
  rateLimitAttempts?: number;
};

function environmentValue(name: string): string | undefined {
  const value = process.env[name]?.trim();
  return value || undefined;
}

function positiveEnvironmentInteger(name: string): number | undefined {
  const value = environmentValue(name);
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : undefined;
}

const acceptance: Week12AcceptanceConfig = {
  baseUrl: environmentValue("WEEK12_ACCEPTANCE_BASE_URL"),
  isolationConfirmed: process.env.WEEK12_ACCEPTANCE_ISOLATED === "1",
  ownerUsername: environmentValue("WEEK12_OWNER_USERNAME"),
  ownerPassword: environmentValue("WEEK12_OWNER_PASSWORD"),
  fixtureDatabaseUrl: environmentValue("WEEK12_FIXTURE_DATABASE_URL"),
  inferenceRuntimeUrl: environmentValue("WEEK12_INFERENCE_RUNTIME_URL"),
  inferenceInternalSecret: environmentValue("WEEK12_INFERENCE_INTERNAL_SECRET"),
  mailpitApiUrl: environmentValue("WEEK12_MAILPIT_API_URL"),
  webhookReceiverUrl: environmentValue("WEEK12_WEBHOOK_RECEIVER_URL"),
  webhookReceiverEventsUrl: environmentValue("WEEK12_WEBHOOK_RECEIVER_EVENTS_URL"),
  webhookSigningSecret: environmentValue("WEEK12_WEBHOOK_SIGNING_SECRET"),
  wecomReceiverUrl: environmentValue("WEEK12_WECOM_RECEIVER_URL"),
  wecomReceiverEventsUrl: environmentValue("WEEK12_WECOM_RECEIVER_EVENTS_URL"),
  rateLimitAttempts: positiveEnvironmentInteger("WEEK12_RATE_LIMIT_ATTEMPTS"),
};

const requiredAcceptanceEnvironment = [
  ["WEEK12_ACCEPTANCE_BASE_URL", acceptance.baseUrl],
  ["WEEK12_ACCEPTANCE_ISOLATED=1", acceptance.isolationConfirmed ? "1" : undefined],
  ["WEEK12_OWNER_USERNAME", acceptance.ownerUsername],
  ["WEEK12_OWNER_PASSWORD", acceptance.ownerPassword],
  ["WEEK12_FIXTURE_DATABASE_URL", acceptance.fixtureDatabaseUrl],
  ["WEEK12_INFERENCE_RUNTIME_URL", acceptance.inferenceRuntimeUrl],
  ["WEEK12_INFERENCE_INTERNAL_SECRET", acceptance.inferenceInternalSecret],
  ["WEEK12_MAILPIT_API_URL", acceptance.mailpitApiUrl],
  ["WEEK12_WEBHOOK_RECEIVER_URL", acceptance.webhookReceiverUrl],
  ["WEEK12_WEBHOOK_RECEIVER_EVENTS_URL", acceptance.webhookReceiverEventsUrl],
  ["WEEK12_WEBHOOK_SIGNING_SECRET", acceptance.webhookSigningSecret],
  ["WEEK12_WECOM_RECEIVER_URL", acceptance.wecomReceiverUrl],
  ["WEEK12_WECOM_RECEIVER_EVENTS_URL", acceptance.wecomReceiverEventsUrl],
  ["WEEK12_RATE_LIMIT_ATTEMPTS", acceptance.rateLimitAttempts],
] as const;

const missingAcceptanceEnvironment = requiredAcceptanceEnvironment
  .filter(([, value]) => value === undefined)
  .map(([name]) => name);
const acceptanceEnabled = process.env.RUN_WEEK12_BROWSER_ACCEPTANCE === "1"
  && missingAcceptanceEnvironment.length === 0;

function required<T>(value: T | undefined, name: string): T {
  if (value === undefined) {
    throw new Error(`${name} must be configured for isolated Week 12 acceptance`);
  }
  return value;
}

function origin(baseUrl: string, pathname: string): string {
  return new URL(pathname, `${baseUrl.replace(/\/$/, "")}/`).toString();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function responseRecord(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`${label} did not return a JSON object`);
  }
  return value;
}

function stringField(value: unknown, field: string, label: string): string {
  const record = responseRecord(value, label);
  const fieldValue = record[field];
  if (typeof fieldValue !== "string" || fieldValue.length === 0) {
    throw new Error(`${label} did not return ${field}`);
  }
  return fieldValue;
}

function items(value: unknown, label: string): Record<string, unknown>[] {
  const collection = responseRecord(value, label).items;
  if (!Array.isArray(collection) || collection.some((item) => !isRecord(item))) {
    throw new Error(`${label} did not return an item list`);
  }
  return collection;
}

function fixtureEnvironment(config: Week12AcceptanceConfig): NodeJS.ProcessEnv {
  if (!config.isolationConfirmed) {
    throw new Error("WEEK12_ACCEPTANCE_ISOLATED=1 is required before running fixture writes");
  }
  return {
    ...process.env,
    DATABASE_URL: required(config.fixtureDatabaseUrl, "WEEK12_FIXTURE_DATABASE_URL"),
    INFERENCE_RUNTIME_URL: required(config.inferenceRuntimeUrl, "WEEK12_INFERENCE_RUNTIME_URL"),
    INFERENCE_INTERNAL_SECRET: required(
      config.inferenceInternalSecret,
      "WEEK12_INFERENCE_INTERNAL_SECRET",
    ),
  };
}

function runInferenceFixture<T>(
  config: Week12AcceptanceConfig,
  name: string,
  ...args: string[]
): T {
  const script = path.resolve(import.meta.dirname, "fixtures", name);
  try {
    const output = execFileSync(resolveE2ePython(), [script, ...args], {
      cwd: path.resolve(import.meta.dirname, "../../backend"),
      encoding: "utf-8",
      env: fixtureEnvironment(config),
      stdio: ["ignore", "pipe", "pipe"],
    });
    return JSON.parse(output) as T;
  } catch {
    throw new Error(`${name} failed against the isolated acceptance fixture`);
  }
}

const ADVANCE_ROLLOUT_ONCE = String.raw`
import json
import sys
import uuid

import app.main
from app.config import settings
from app.database import SessionLocal
from app.models.model_registry import DeploymentRollout
from app.services.inference_rollout import InferenceRolloutService
from app.services.inference_runtime_client import InferenceRuntimeClient

rollout_id = uuid.UUID(sys.argv[1])
observation = json.loads(sys.argv[2])
secret = settings.resolved_inference_internal_secret
if secret is None or not settings.inference_runtime_url:
    raise RuntimeError("inference runtime is not configured")
runtime = InferenceRuntimeClient(
    settings.inference_runtime_url,
    secret.get_secret_value(),
    load_timeout_seconds=settings.inference_load_timeout_seconds,
    predict_timeout_seconds=settings.inference_predict_timeout_seconds,
)
with SessionLocal() as db:
    rollout = db.get(DeploymentRollout, rollout_id)
    if rollout is None:
        raise RuntimeError("rollout not found")
    advanced = InferenceRolloutService(runtime).advance(
        db,
        rollout_id,
        expected_lock_version=rollout.lock_version,
        observation=observation,
    )
    print(json.dumps({
        "state": advanced.state,
        "current_step": advanced.current_step,
        "lock_version": advanced.lock_version,
    }))
`;

function advanceRolloutOnce(
  config: Week12AcceptanceConfig,
  rolloutId: string,
  observation: { error_rate: number; p95_ms: number },
): RolloutFixtureResult {
  try {
    const output = execFileSync(
      resolveE2ePython(),
      ["-c", ADVANCE_ROLLOUT_ONCE, rolloutId, JSON.stringify(observation)],
      {
        cwd: path.resolve(import.meta.dirname, "../../backend"),
        encoding: "utf-8",
        env: fixtureEnvironment(config),
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    return JSON.parse(output) as RolloutFixtureResult;
  } catch {
    throw new Error("isolated rollout advance fixture failed");
  }
}

async function loginAs(page: Page, credentials: Credentials, baseUrl: string): Promise<void> {
  await page.goto(origin(baseUrl, "/login"));
  await page.getByPlaceholder(/(?:\u7528\u6237\u540d|Username)/).fill(credentials.username);
  await page.getByPlaceholder(/(?:\u5bc6\u7801|Password)/).fill(credentials.password);
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/$/);
}

async function register(page: Page, credentials: Credentials): Promise<ApiResult> {
  return page.evaluate(async (candidate) => {
    const response = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(candidate),
    });
    const text = await response.text();
    let body: unknown = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }
    return {
      status: response.status,
      body,
      retryAfter: response.headers.get("Retry-After"),
    };
  }, credentials);
}

async function api(
  page: Page,
  requestPath: string,
  method: ApiMethod,
  payload?: unknown,
  extraHeaders: Record<string, string> = {},
): Promise<ApiResult> {
  return page.evaluate(async ({ path: requestUrl, requestMethod, requestPayload, headers }) => {
    const token = localStorage.getItem("token") || "";
    const response = await fetch(requestUrl, {
      method: requestMethod,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(requestPayload === undefined ? {} : { "Content-Type": "application/json" }),
        ...headers,
      },
      ...(requestPayload === undefined ? {} : { body: JSON.stringify(requestPayload) }),
    });
    const text = await response.text();
    let body: unknown = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }
    return {
      status: response.status,
      body,
      retryAfter: response.headers.get("Retry-After"),
    };
  }, {
    path: requestPath,
    requestMethod: method,
    requestPayload: payload,
    headers: extraHeaders,
  });
}

async function expectStatus(
  page: Page,
  requestPath: string,
  method: ApiMethod,
  expectedStatus: number,
  payload?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<ApiResult> {
  const result = await api(page, requestPath, method, payload, extraHeaders);
  expect(result.status, `${method} ${requestPath}`).toBe(expectedStatus);
  return result;
}

async function createRolePage(
  browser: Browser,
  credentials: Credentials,
  baseUrl: string,
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await loginAs(page, credentials, baseUrl);
  return { context, page };
}

async function waitForControlledEvent(
  request: APIRequestContext,
  eventsUrl: string,
  matches: (body: string) => boolean,
  receiver: string,
): Promise<string> {
  const deadline = Date.now() + 20_000;
  let lastStatus = 0;
  while (Date.now() < deadline) {
    const response = await request.get(eventsUrl, { timeout: 5_000 });
    lastStatus = response.status();
    if (lastStatus === 200) {
      const body = await response.text();
      if (matches(body)) return body;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`${receiver} did not expose a matching controlled-receiver event (last status ${lastStatus})`);
}

function assertSafeDelivery(serialized: string, secrets: string[]): void {
  const normalized = serialized.toLowerCase();
  for (const forbidden of ["records", "predictions", "storage_uri", "traceback"]) {
    expect(normalized.includes(forbidden), `delivery leaked ${forbidden}`).toBe(false);
  }
  for (const secret of secrets) {
    expect(serialized.includes(secret), "delivery leaked a configured secret").toBe(false);
  }
}

function endpointId(endpoint: unknown, label: string): string {
  return stringField(endpoint, "id", label);
}

async function createEndpoint(
  ownerPage: Page,
  projectId: string,
  name: string,
  kind: "in_app" | "wecom" | "email" | "webhook",
  config: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const result = await expectStatus(
    ownerPage,
    `/api/projects/${projectId}/notification-endpoints`,
    "POST",
    201,
    { name, kind, config },
  );
  return responseRecord(result.body, `${kind} endpoint`);
}

async function testEndpoint(
  ownerPage: Page,
  projectId: string,
  id: string,
): Promise<void> {
  const result = await expectStatus(
    ownerPage,
    `/api/projects/${projectId}/notification-endpoints/${id}/test`,
    "POST",
    200,
  );
  const response = responseRecord(result.body, "notification endpoint test");
  expect(response.status).toBe("sent");
  expect(response.error_code).toBeNull();
}

test.describe("Week 12 isolated acceptance", () => {
  test.skip(
    !acceptanceEnabled,
    `requires RUN_WEEK12_BROWSER_ACCEPTANCE=1 and ${missingAcceptanceEnvironment.join(", ") || "the isolated acceptance environment"}; skipped is not an acceptance pass`,
  );

  test("four roles, rollout lifecycle, notifications, rate limit, and audit redaction", async ({ page, browser, request }) => {
    test.setTimeout(240_000);

    const baseUrl = required(acceptance.baseUrl, "WEEK12_ACCEPTANCE_BASE_URL");
    const owner: Credentials = {
      username: required(acceptance.ownerUsername, "WEEK12_OWNER_USERNAME"),
      password: required(acceptance.ownerPassword, "WEEK12_OWNER_PASSWORD"),
    };
    const mailpitApiUrl = required(acceptance.mailpitApiUrl, "WEEK12_MAILPIT_API_URL");
    const webhookReceiverUrl = required(acceptance.webhookReceiverUrl, "WEEK12_WEBHOOK_RECEIVER_URL");
    const webhookReceiverEventsUrl = required(
      acceptance.webhookReceiverEventsUrl,
      "WEEK12_WEBHOOK_RECEIVER_EVENTS_URL",
    );
    const webhookSigningSecret = required(
      acceptance.webhookSigningSecret,
      "WEEK12_WEBHOOK_SIGNING_SECRET",
    );
    const wecomReceiverUrl = required(acceptance.wecomReceiverUrl, "WEEK12_WECOM_RECEIVER_URL");
    const wecomReceiverEventsUrl = required(
      acceptance.wecomReceiverEventsUrl,
      "WEEK12_WECOM_RECEIVER_EVENTS_URL",
    );
    const rateLimitAttempts = required(
      acceptance.rateLimitAttempts,
      "WEEK12_RATE_LIMIT_ATTEMPTS",
    );

    const unique = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const editor: Credentials = {
      username: `week12-editor-${unique}`,
      password: `week12-editor-password-${unique}`,
    };
    const operator: Credentials = {
      username: `week12-operator-${unique}`,
      password: `week12-operator-password-${unique}`,
    };
    const viewer: Credentials = {
      username: `week12-viewer-${unique}`,
      password: `week12-viewer-password-${unique}`,
    };
    const outsider: Credentials = {
      username: `week12-outsider-${unique}`,
      password: `week12-outsider-password-${unique}`,
    };
    const projectName = `Week 12 acceptance ${unique}`;
    const emailRecipient = `week12-${unique}@acceptance.invalid`;

    await loginAs(page, owner, baseUrl);
    for (const role of [editor, operator, viewer, outsider]) {
      expect((await register(page, role)).status).toBe(200);
    }

    const projectResponse = await expectStatus(page, "/api/projects", "POST", 201, {
      name: projectName,
      description: "Isolated Week 12 browser acceptance",
    });
    const projectId = stringField(projectResponse.body, "id", "project creation");

    for (const [credentials, role] of [
      [editor, "editor"],
      [operator, "operator"],
      [viewer, "viewer"],
    ] as const) {
      await expectStatus(page, `/api/projects/${projectId}/members`, "POST", 201, {
        username: credentials.username,
        role,
      });
    }

    const directory = await expectStatus(
      page,
      `/api/projects/${projectId}/notification-recipients`,
      "GET",
      200,
    );
    const ownerDirectoryEntry = items(directory.body, "notification recipient directory").find(
      (item) => item.username === owner.username,
    );
    if (!ownerDirectoryEntry) {
      throw new Error("owner is absent from the notification recipient directory");
    }
    const ownerId = stringField(ownerDirectoryEntry, "user_id", "owner directory entry");

    const endpointNames = {
      inApp: `week12-in-app-${unique}`,
      wecom: `week12-wecom-${unique}`,
      email: `week12-email-${unique}`,
      webhook: `week12-webhook-${unique}`,
    };
    const inAppEndpoint = await createEndpoint(page, projectId, endpointNames.inApp, "in_app", {
      recipient_user_ids: [ownerId],
    });
    const wecomEndpoint = await createEndpoint(page, projectId, endpointNames.wecom, "wecom", {
      url: wecomReceiverUrl,
    });
    const emailEndpoint = await createEndpoint(page, projectId, endpointNames.email, "email", {
      to: [emailRecipient],
      cc: [],
    });
    const webhookEndpoint = await createEndpoint(page, projectId, endpointNames.webhook, "webhook", {
      url: webhookReceiverUrl,
      headers: {},
      signature_mode: "hmac-sha256",
      signing_secret: webhookSigningSecret,
    });

    const unreadBaselineResponse = await expectStatus(page, "/api/notifications/unread-count", "GET", 200);
    const unreadBaseline = responseRecord(unreadBaselineResponse.body, "unread notification count").count;
    if (typeof unreadBaseline !== "number" || !Number.isInteger(unreadBaseline) || unreadBaseline < 0) {
      throw new Error("unread notification count is invalid before controlled delivery");
    }

    await page.goto(origin(baseUrl, `/projects/${projectId}`));
    const governance = page.getByLabel(/(?:\u9879\u76ee\u6cbb\u7406|Project governance)/);
    await governance.getByRole("tab", { name: /(?:\u901a\u77e5|Notifications)/ }).click();
    for (const endpointName of Object.values(endpointNames)) {
      await expect(governance.getByText(endpointName, { exact: true })).toBeVisible();
    }
    const inAppRow = governance.getByRole("row", { name: new RegExp(endpointNames.inApp) });
    const inAppUiDelivery = page.waitForResponse((response) => (
      response.request().method() === "POST"
      && response.url().endsWith(`/api/projects/${projectId}/notification-endpoints/${endpointId(inAppEndpoint, "in-app endpoint")}/test`)
    ));
    await inAppRow.getByRole("button", { name: /(?:\u6d4b\u8bd5\u7aef\u70b9|Test endpoint)/ }).click();
    expect((await inAppUiDelivery).status()).toBe(200);

    await testEndpoint(page, projectId, endpointId(wecomEndpoint, "WeCom endpoint"));
    await testEndpoint(page, projectId, endpointId(emailEndpoint, "email endpoint"));
    await testEndpoint(page, projectId, endpointId(webhookEndpoint, "webhook endpoint"));

    const inAppNotifications = await expectStatus(page, "/api/notifications", "GET", 200);
    const inAppNotice = items(inAppNotifications.body, "in-app notifications").find(
      (item) => item.event_type === "rollout.completed" && item.project_id === projectId,
    );
    if (!inAppNotice) {
      throw new Error("controlled in-app receiver did not receive the notification");
    }
    const notificationId = stringField(inAppNotice, "id", "in-app notification");
    const unreadBeforeRead = await expectStatus(page, "/api/notifications/unread-count", "GET", 200);
    expect(responseRecord(unreadBeforeRead.body, "unread notification count").count).toBe(unreadBaseline + 1);
    await expectStatus(page, `/api/notifications/${notificationId}/read`, "PATCH", 200);
    const unreadAfterRead = await expectStatus(page, "/api/notifications/unread-count", "GET", 200);
    expect(responseRecord(unreadAfterRead.body, "unread notification count").count).toBe(unreadBaseline);
    await expectStatus(page, `/api/notifications/${notificationId}/archive`, "PATCH", 200);

    const webhookEvent = await waitForControlledEvent(
      request,
      webhookReceiverEventsUrl,
      (body) => body.includes(projectId) && body.includes("rollout.completed"),
      "generic Webhook receiver",
    );
    assertSafeDelivery(webhookEvent, [webhookSigningSecret]);
    const wecomEvent = await waitForControlledEvent(
      request,
      wecomReceiverEventsUrl,
      (body) => body.includes(endpointId(wecomEndpoint, "WeCom endpoint")) && body.includes("rollout.completed"),
      "WeCom receiver",
    );
    assertSafeDelivery(wecomEvent, []);
    const emailEvent = await waitForControlledEvent(
      request,
      mailpitApiUrl,
      (body) => body.includes(emailRecipient) && body.includes("rollout.completed"),
      "Mailpit receiver",
    );
    assertSafeDelivery(emailEvent, []);

    const firstSources = runInferenceFixture<SeededInferenceSources>(
      acceptance,
      "seed_inference_model.py",
      projectId,
    );
    const secondSources = runInferenceFixture<SeededInferenceSources>(
      acceptance,
      "seed_inference_model.py",
      projectId,
    );
    const sourceIds = [...firstSources.model_library_ids, ...secondSources.model_library_ids];
    expect(sourceIds).toHaveLength(4);

    const modelResponse = await expectStatus(page, `/api/projects/${projectId}/registered-models`, "POST", 201, {
      name: `Week 12 model ${unique}`,
      description: "isolated acceptance model",
    });
    const modelId = stringField(modelResponse.body, "id", "registered model");
    const versionIds: string[] = [];
    for (const sourceId of sourceIds.slice(0, 3)) {
      const versionResponse = await expectStatus(
        page,
        `/api/registered-models/${modelId}/versions`,
        "POST",
        201,
        { source_kind: "platform_joblib", source_model_library_id: sourceId },
      );
      const versionId = stringField(versionResponse.body, "id", "model version");
      versionIds.push(versionId);
      await expectStatus(page, `/api/model-versions/${versionId}/approve`, "POST", 200, { comment: "acceptance" });
    }
    const [stableVersionId, failedCandidateVersionId, candidateVersionId] = versionIds;
    if (!stableVersionId || !failedCandidateVersionId || !candidateVersionId) {
      throw new Error("acceptance fixture did not produce three registered model versions");
    }

    const deploymentResponse = await expectStatus(
      page,
      `/api/projects/${projectId}/inference-deployments`,
      "POST",
      201,
      { name: `week12-deployment-${unique}`, model_version_id: stableVersionId },
    );
    const deploymentId = stringField(deploymentResponse.body, "id", "inference deployment");
    await expectStatus(page, `/api/inference-deployments/${deploymentId}/start`, "POST", 200);

    const thresholdRolloutResponse = await expectStatus(
      page,
      `/api/inference-deployments/${deploymentId}/rollouts`,
      "POST",
      201,
      {
        strategy: "canary",
        targets: [{ model_version_id: failedCandidateVersionId, weight_bps: 10000 }],
        step_schedule: [0, 1000, 5000, 10000],
        max_error_rate: 0,
        max_p95_ms: 1000,
      },
    );
    const thresholdRolloutId = stringField(thresholdRolloutResponse.body, "id", "threshold rollout");
    const thresholdPreload = runInferenceFixture<RolloutFixtureResult>(
      acceptance,
      "advance_inference_rollout.py",
      thresholdRolloutId,
      "preload",
    );
    expect(thresholdPreload).toMatchObject({ state: "progressing", current_step: 0 });
    const automaticallyRolledBack = advanceRolloutOnce(acceptance, thresholdRolloutId, {
      error_rate: 1,
      p95_ms: 1,
    });
    expect(automaticallyRolledBack).toMatchObject({ state: "rolled_back", current_step: 0 });

    const rolloutResponse = await expectStatus(
      page,
      `/api/inference-deployments/${deploymentId}/rollouts`,
      "POST",
      201,
      {
        strategy: "canary",
        targets: [{ model_version_id: candidateVersionId, weight_bps: 10000 }],
        step_schedule: [0, 1000, 5000, 10000],
        max_error_rate: 0.01,
        max_p95_ms: 1000,
      },
    );
    const rolloutId = stringField(rolloutResponse.body, "id", "rollout");
    const preloaded = runInferenceFixture<RolloutFixtureResult>(
      acceptance,
      "advance_inference_rollout.py",
      rolloutId,
      "preload",
    );
    expect(preloaded).toMatchObject({ state: "progressing", current_step: 0 });
    let progressed = preloaded;
    for (const expectedStep of [1000, 5000, 10000]) {
      progressed = advanceRolloutOnce(acceptance, rolloutId, { error_rate: 0, p95_ms: 1 });
      expect(progressed.current_step).toBe(expectedStep);
    }
    expect(progressed.state).toBe("completed");
    const rolledBack = await expectStatus(
      page,
      `/api/inference-deployments/${deploymentId}/rollouts/${rolloutId}/rollback`,
      "POST",
      200,
      { expected_lock_version: progressed.lock_version },
    );
    expect(responseRecord(rolledBack.body, "manual rollback").state).toBe("rolled_back");

    const createdKey = await expectStatus(
      page,
      `/api/inference-deployments/${deploymentId}/api-keys`,
      "POST",
      201,
      { scopes: ["inference.predict"] },
    );
    const createdKeyRecord = responseRecord(createdKey.body, "API key creation");
    const apiKey = stringField(createdKeyRecord, "plaintext", "API key creation");
    expect(apiKey.startsWith("mli_")).toBe(true);
    const apiKeyList = await expectStatus(
      page,
      `/api/inference-deployments/${deploymentId}/api-keys`,
      "GET",
      200,
    );
    expect(JSON.stringify(apiKeyList.body).includes(apiKey), "API key must be shown only once").toBe(false);

    const productionPredictPath = `/api/v1/inference/${deploymentId}/predict`;
    let rateLimited: ApiResult | undefined;
    for (let attempt = 0; attempt < rateLimitAttempts; attempt += 1) {
      const prediction = await api(
        page,
        productionPredictPath,
        "POST",
        { records: [{ current: 0, voltage: 0 }] },
        { "X-Inference-Api-Key": apiKey },
      );
      if (prediction.status === 429) {
        rateLimited = prediction;
        break;
      }
      expect([200, 429]).toContain(prediction.status);
    }
    if (!rateLimited) {
      throw new Error("configured rate-limit attempt count did not produce HTTP 429");
    }
    expect(typeof rateLimited.retryAfter === "string" && /^[1-9][0-9]*$/.test(rateLimited.retryAfter)).toBe(true);

    const editorSession = await createRolePage(browser, editor, baseUrl);
    const operatorSession = await createRolePage(browser, operator, baseUrl);
    const viewerSession = await createRolePage(browser, viewer, baseUrl);
    const outsiderSession = await createRolePage(browser, outsider, baseUrl);
    try {
      await expectStatus(editorSession.page, `/api/projects/${projectId}/notification-endpoints`, "GET", 200);
      await expectStatus(
        editorSession.page,
        `/api/inference-deployments/${deploymentId}/api-keys`,
        "POST",
        201,
        { scopes: ["inference.predict"] },
      );

      await expectStatus(operatorSession.page, `/api/projects/${projectId}/notification-endpoints`, "GET", 200);
      await expectStatus(
        operatorSession.page,
        `/api/projects/${projectId}/notification-endpoints`,
        "POST",
        403,
        {
          kind: "in_app",
          name: `operator-denied-${unique}`,
          config: { recipient_user_ids: [ownerId] },
        },
      );
      await expectStatus(
        operatorSession.page,
        `/api/inference-deployments/${deploymentId}/predict`,
        "POST",
        200,
        { records: [{ current: 0, voltage: 0 }] },
      );

      await expectStatus(viewerSession.page, `/api/projects/${projectId}/notification-endpoints`, "GET", 200);
      await expectStatus(
        viewerSession.page,
        `/api/inference-deployments/${deploymentId}/predict`,
        "POST",
        403,
        { records: [{ current: 0, voltage: 0 }] },
      );
      await expectStatus(viewerSession.page, `/api/projects/${projectId}/audit-events`, "GET", 403);

      for (const hiddenPath of [
        `/api/projects/${projectId}`,
        `/api/projects/${projectId}/members`,
        `/api/projects/${projectId}/notification-endpoints`,
        `/api/inference-deployments/${deploymentId}`,
      ]) {
        await expectStatus(outsiderSession.page, hiddenPath, "GET", 404);
      }
    } finally {
      await Promise.all([
        editorSession.context.close(),
        operatorSession.context.close(),
        viewerSession.context.close(),
        outsiderSession.context.close(),
      ]);
    }

    const audit = await expectStatus(page, `/api/projects/${projectId}/audit-events?limit=200`, "GET", 200);
    const auditText = JSON.stringify(audit.body);
    for (const forbidden of ["records", "predictions", "storage_uri", "traceback"]) {
      expect(auditText.toLowerCase().includes(forbidden), `audit leaked ${forbidden}`).toBe(false);
    }
    expect(auditText.includes(webhookSigningSecret), "audit leaked the Webhook signing secret").toBe(false);
    expect(auditText.includes(apiKey), "audit leaked the one-time API key").toBe(false);
    expect(items(audit.body, "project audit events").some(
      (item) => item.action === "inference_rollout.rollback" && item.result === "success",
    )).toBe(true);
  });
});
