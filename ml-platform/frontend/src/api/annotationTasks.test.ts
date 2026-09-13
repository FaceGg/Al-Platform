import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import { createGenericAnnotationTask, type GenericTaskCreatePayload } from "./annotationTasks";

describe("annotation task client", () => {
  beforeEach(() => vi.restoreAllMocks());

  const payload = (mode: GenericTaskCreatePayload["mode"]): GenericTaskCreatePayload => ({
    project_id: "project-1",
    dataset_version_id: "version-1",
    label_schema_id: "schema-1",
    mode,
    sample_scope: { kind: "all" },
    visible_columns: ["feature"],
    instructions: "",
    configuration: mode === "automatic"
      ? { model_artifact_id: "artifact-1", search_strength: "strong" }
      : {},
  });

  it("uses the manual generic task endpoint and idempotent request headers", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { id: "task-1" } });
    vi.stubGlobal("crypto", { randomUUID: () => "request-1" });

    await createGenericAnnotationTask(payload("manual"), "idempotency-1");

    expect(post).toHaveBeenCalledWith(
      "/annotation-tasks",
      expect.objectContaining({ mode: "manual" }),
      { headers: { "X-Request-ID": "request-1", "Idempotency-Key": "idempotency-1" } }, // gitleaks:allow
    );
  });

  it("uses the AutoML endpoint and never adds max_trials", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { id: "task-2" } });
    vi.stubGlobal("crypto", { randomUUID: () => "request-2" });

    await createGenericAnnotationTask(payload("automatic"), "idempotency-2");

    expect(post).toHaveBeenCalledWith(
      "/automl-tasks",
      expect.objectContaining({
        mode: "automatic",
        configuration: { model_artifact_id: "artifact-1", search_strength: "strong" },
      }),
      { headers: { "X-Request-ID": "request-2", "Idempotency-Key": "idempotency-2" } }, // gitleaks:allow
    );
    expect(post.mock.calls[0][1]).not.toHaveProperty("max_trials");
  });
});
