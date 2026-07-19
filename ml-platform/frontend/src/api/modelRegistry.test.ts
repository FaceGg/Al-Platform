import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import {
  approveModelVersion,
  createDeployment,
  createRegisteredModel,
  listDeployments,
  listRegisteredModels,
  listModelVersions,
  predictDeployment,
  registerOnnxVersion,
  registerPlatformVersion,
  rejectModelVersion,
  startDeployment,
  stopDeployment,
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
});
