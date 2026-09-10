import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import { createModelExport, getModelExport } from "./modelExports";

vi.mock("./client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));

const client = vi.mocked(apiClient);

describe("modelExports API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("creates and reads a signed export receipt", async () => {
    client.post.mockResolvedValue({ data: { id: "export-1", status: "queued" } });
    client.get.mockResolvedValue({ data: { id: "export-1", status: "ready", checksum: "sha256:x" } });
    await createModelExport("project-1", { model_version_id: "version-1", include_annotation: true, export_kind: "predict" });
    await getModelExport("export-1");
    expect(client.post).toHaveBeenCalledWith("/projects/project-1/model-exports", { model_version_id: "version-1", include_annotation: true, export_kind: "predict" });
    expect(client.get).toHaveBeenCalledWith("/model-exports/export-1");
  });
});
