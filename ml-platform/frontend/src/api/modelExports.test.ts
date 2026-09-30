import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import { createModelExport, getModelExport } from "./modelExports";

vi.mock("./client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));

const client = vi.mocked(apiClient);

describe("modelExports API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("creates a version-scoped export with an idempotency key and reads its status", async () => {
    client.post.mockResolvedValue({ data: { id: "export-1", status: "queued" } });
    client.get.mockResolvedValue({ data: { id: "export-1", status: "completed", manifest_sha256: "sha256:x" } });
    await createModelExport("version-1", { model_version_id: "version-1", export_kind: "predict" });
    await getModelExport("export-1");
    expect(client.post).toHaveBeenCalledWith(
      "/model-versions/version-1/exports",
      { model_version_id: "version-1", include_runtime: true },
      { headers: { "Idempotency-Key": expect.any(String) } },
    );
    expect(client.get).toHaveBeenCalledWith("/model-exports/export-1");
  });

  it("binds annotate exports to the base annotation revision", async () => {
    client.post.mockResolvedValue({ data: { id: "export-2", status: "queued" } });
    await createModelExport("version-1", { model_version_id: "version-1", export_kind: "annotate" });
    expect(client.post).toHaveBeenCalledWith(
      "/model-versions/version-1/exports",
      { model_version_id: "version-1", include_runtime: true, annotation_task_revision: 0 },
      { headers: { "Idempotency-Key": expect.any(String) } },
    );
  });
});
