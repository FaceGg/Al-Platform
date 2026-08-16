import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import {
  approveModelVersion,
  createInferenceApiKey,
  createDeployment,
  createRegisteredModel,
  createRollout,
  exportModelCard,
  getModelCard,
  listInferenceApiKeys,
  listInferenceMetrics,
  listInferenceMetricWindow,
  listInferenceRequestLogs,
  listDeployments,
  listRegisteredModels,
  listModelVersions,
  listRollouts,
  pauseRollout,
  predictDeployment,
  registerOnnxVersion,
  registerPlatformVersion,
  rejectModelVersion,
  resumeRollout,
  revokeInferenceApiKey,
  rollbackRollout,
  rotateInferenceApiKey,
  startDeployment,
  stopDeployment,
  updateModelCardGuidance,
  uploadOnnxArtifact,
} from "./modelRegistry";

describe("modelRegistry client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("normalizes model, version, and deployment lists", async () => {
    const get = vi.spyOn(apiClient, "get")
      .mockResolvedValueOnce({ data: { items: [{ id: "m1" }] } })
      .mockResolvedValueOnce({ data: [{ id: "v1" }] })
      .mockResolvedValueOnce({ data: { items: [{ id: "d1" }] } });
    expect(await listRegisteredModels("p1")).toEqual([{ id: "m1" }]);
    expect(await listModelVersions("m1")).toEqual([{ id: "v1" }]);
    expect(await listDeployments("p1")).toEqual([{ id: "d1" }]);
    expect(get.mock.calls.map(([url]) => url)).toEqual([
      "/projects/p1/registered-models",
      "/registered-models/m1/versions",
      "/projects/p1/inference-deployments",
    ]);
  });

  it("sends exact registry and lifecycle payloads", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { id: "ok" } });
    await createRegisteredModel("p1", { name: "Weld", description: "Classifier" });
    await registerPlatformVersion("m1", "library-1");
    await registerOnnxVersion("m1", {
      source_artifact_id: "artifact-1",
      feature_schema: [{ name: "current", dtype: "float64" }],
      output_schema: { name: "fault", dtype: "int64", task: "classification" },
    });
    await approveModelVersion("v1", "ready");
    await rejectModelVersion("v2", "invalid schema");
    await createDeployment("p1", { name: "line-a", model_version_id: "v1" });
    await startDeployment("d1");
    await stopDeployment("d1");
    await predictDeployment("d1", [{ current: 1.2, voltage: 3.4 }]);
    expect(post.mock.calls).toEqual([
      ["/projects/p1/registered-models", { name: "Weld", description: "Classifier" }],
      ["/registered-models/m1/versions", { source_kind: "platform_joblib", source_model_library_id: "library-1" }],
      ["/registered-models/m1/versions", { source_kind: "onnx_artifact", source_artifact_id: "artifact-1", feature_schema: [{ name: "current", dtype: "float64" }], output_schema: { name: "fault", dtype: "int64", task: "classification" } }],
      ["/model-versions/v1/approve", { comment: "ready" }],
      ["/model-versions/v2/reject", { comment: "invalid schema" }],
      ["/projects/p1/inference-deployments", { name: "line-a", model_version_id: "v1" }],
      ["/inference-deployments/d1/start"],
      ["/inference-deployments/d1/stop"],
      ["/inference-deployments/d1/predict", { records: [{ current: 1.2, voltage: 3.4 }] }],
    ]);
  });

  it("uploads ONNX through multipart without overriding browser boundary", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { id: "a1" } });
    const file = new File(["onnx"], "weld.onnx", { type: "application/octet-stream" });
    await uploadOnnxArtifact("p1", file);
    expect(post).toHaveBeenCalledOnce();
    expect(post.mock.calls[0][0]).toBe("/projects/p1/model-artifacts");
    const body = post.mock.calls[0][1] as FormData;
    expect(body.get("file")).toBe(file);
    expect(post.mock.calls[0]).toHaveLength(2);
  });

  it("uses frozen rollout, key, telemetry, and model-card contracts", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { id: "r1", state: "pending", lock_version: 1, plaintext: "once-only" },
    });
    const patch = vi.spyOn(apiClient, "patch").mockResolvedValue({ data: { id: "card-1" } });
    const get = vi.spyOn(apiClient, "get")
      .mockResolvedValueOnce({ data: { items: [{ id: "r1", state: "pending" }], total: 1 } })
      .mockResolvedValueOnce({ data: { items: [{ id: "k1", prefix: "pk_live_123" }], total: 1 } })
      .mockResolvedValueOnce({ data: { items: [], summary: { request_count: 0 }, page: 1, page_size: 100 } })
      .mockResolvedValueOnce({ data: { items: [], page: 1, page_size: 100 } })
      .mockResolvedValueOnce({ data: { id: "card-1", operational_guidance: "Observe output drift." } })
      .mockResolvedValueOnce({ data: { id: "card-1", export: "markdown" } });
    const metricWindow = { since: "2026-07-20T00:00:00Z", until: "2026-07-20T01:00:00Z", page: 1, page_size: 100 };

    await createRollout("d1", {
      strategy: "canary",
      targets: [{ model_version_id: "v2", weight_bps: 10000 }],
    });
    await pauseRollout("d1", "r0");
    await pauseRollout("d1", "r1", 1);
    await resumeRollout("d1", "r1", 2);
    await rollbackRollout("d1", "r1", 3);
    await createInferenceApiKey("d1", { scopes: ["inference.predict"] });
    await rotateInferenceApiKey("k1");
    await revokeInferenceApiKey("k1");
    await listRollouts("d1");
    await listInferenceApiKeys("d1");
    await listInferenceMetrics("d1", metricWindow);
    await listInferenceRequestLogs("d1", metricWindow);
    await getModelCard("v2");
    await updateModelCardGuidance("card-1", "Observe output drift.");
    await exportModelCard("card-1");

    expect(post).toHaveBeenCalledWith("/inference-deployments/d1/rollouts", {
      strategy: "canary",
      targets: [{ model_version_id: "v2", weight_bps: 10000 }],
    });
    expect(post).toHaveBeenCalledWith("/inference-deployments/d1/rollouts/r0/pause", {});
    expect(post).toHaveBeenCalledWith("/inference-deployments/d1/rollouts/r1/pause", { expected_lock_version: 1 });
    expect(post).toHaveBeenCalledWith("/inference-deployments/d1/rollouts/r1/resume", { expected_lock_version: 2 });
    expect(post).toHaveBeenCalledWith("/inference-deployments/d1/rollouts/r1/rollback", { expected_lock_version: 3 });
    expect(post).toHaveBeenCalledWith("/inference-deployments/d1/api-keys", { scopes: ["inference.predict"] });
    expect(post).toHaveBeenCalledWith("/inference-api-keys/k1/rotate");
    expect(post).toHaveBeenCalledWith("/inference-api-keys/k1/revoke");
    expect(get).toHaveBeenCalledWith("/inference-deployments/d1/metrics", { params: metricWindow });
    expect(get).toHaveBeenCalledWith("/inference-deployments/d1/request-logs", { params: metricWindow });
    expect(patch).toHaveBeenCalledWith("/model-cards/card-1/guidance", { operational_guidance: "Observe output drift." });
    expect(get).toHaveBeenCalledWith("/model-cards/card-1/export");
  });

  it("does not log one-time API-key plaintext", async () => {
    vi.spyOn(apiClient, "post").mockResolvedValue({ data: { id: "k1", plaintext: "do-not-log" } });
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);

    await createInferenceApiKey("d1", { scopes: ["inference.predict"] });

    expect(log).not.toHaveBeenCalled();
  });

  it("loads every metrics page before reporting a time-window summary", async () => {
    const buckets = Array.from({ length: 200 }, (_, index) => ({
      bucket_start: `2026-07-20T00:${String(index).padStart(2, "0")}:00Z`,
      request_count: 1,
      success_count: 1,
      error_count: 0,
      limited_count: 0,
      load_failure_count: 0,
      latency_buckets: { "5": 1 },
      traffic_weights: {},
    }));
    const get = vi.spyOn(apiClient, "get")
      .mockResolvedValueOnce({ data: { items: buckets, summary: {}, page: 1, page_size: 200 } })
      .mockResolvedValueOnce({ data: { items: [{ ...buckets[0], bucket_start: "2026-07-20T03:20:00Z" }], summary: {}, page: 2, page_size: 200 } });
    const window = { since: "2026-07-20T00:00:00Z", until: "2026-07-21T00:00:00Z" };

    const result = await listInferenceMetricWindow("d1", window);

    expect(get).toHaveBeenNthCalledWith(1, "/inference-deployments/d1/metrics", { params: { ...window, page: 1, page_size: 200 } });
    expect(get).toHaveBeenNthCalledWith(2, "/inference-deployments/d1/metrics", { params: { ...window, page: 2, page_size: 200 } });
    expect(result.items).toHaveLength(201);
    expect(result.summary.request_count).toBe(201);
    expect(result.summary.p95_latency_ms).toBe(5);
  });
});
