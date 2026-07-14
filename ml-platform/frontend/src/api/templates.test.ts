import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import { getTemplate, instantiateTemplate } from "./templates";

describe("template API", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("loads industrial template metadata", async () => {
    const detail = {
      id: "weld_quality",
      target_column: "Fault",
      required_columns: ["Car Body", "Welding Spot", "Date", "Fault"],
      parameters: [{ key: "n_estimators", label: "Trees", type: "int", default: 100 }],
    };
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: detail });

    await expect(getTemplate("weld_quality")).resolves.toEqual(detail);
    expect(get).toHaveBeenCalledWith("/templates/weld_quality");
  });

  it("instantiates with an artifact JSON payload", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { workflow_id: "workflow-1", template_id: "weld_quality" },
    });

    await instantiateTemplate("weld_quality", {
      project_id: "project-1",
      dataset_artifact_id: "artifact-1",
      parameters: { n_estimators: 80 },
    });

    expect(post).toHaveBeenCalledWith("/templates/weld_quality/instantiate", {
      project_id: "project-1",
      dataset_artifact_id: "artifact-1",
      parameters: { n_estimators: 80 },
    });
  });
});
