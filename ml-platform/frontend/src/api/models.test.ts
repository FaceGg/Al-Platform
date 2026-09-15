import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import { listAnnotationModelVersions } from "./models";

describe("models client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("lists project-scoped enabled model versions for automatic annotation", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({
      data: { items: [{
        id: "model-version-1",
        registered_model_id: "registered-1",
        model_name: "quality-model",
        version_number: 1,
        algorithm: "RandomForestClassifier",
        feature_schema: [{ name: "feature", dtype: "float64" }],
        output_contract: {
          model_version_id: "model-version-1",
          registered_model_id: "registered-1",
          model_name: "quality-model",
          version_number: 1,
          columns: [{ machine_key: "label", display_name: "Label", value_type: "string", required: true }],
          contract_hash: "sha256:contract",
        },
      }] },
    });

    await expect(listAnnotationModelVersions("project/1")).resolves.toHaveLength(1);
    expect(get).toHaveBeenCalledWith("/projects/project%2F1/annotation-model-versions");
  });
});
