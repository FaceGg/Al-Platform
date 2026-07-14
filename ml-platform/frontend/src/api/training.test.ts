import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import { createTrainingJob, getTrainingJob, listTrainingJobs } from "./training";

describe("training API", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("creates training from a dataset artifact", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { job_id: "job-1", status: "started" },
    });

    await createTrainingJob({
      project_id: "project-1",
      dataset_artifact_id: "artifact-1",
      name: "weld-quality",
      operator_id: "random_forest",
      params: { target_column: "quality" },
    });

    expect(post).toHaveBeenCalledWith("/training/run", {
      project_id: "project-1",
      dataset_artifact_id: "artifact-1",
      name: "weld-quality",
      operator_id: "random_forest",
      params: { target_column: "quality" },
    });
  });

  it("preserves lineage fields in list and detail responses", async () => {
    const job = {
      id: "job-1",
      dataset_artifact_id: "dataset-1",
      model_artifact_id: "model-1",
      model_library_id: "library-1",
      feature_schema: [{ name: "current", dtype: "float64" }],
      target_schema: { name: "quality", dtype: "int64" },
      preprocessing: { missing_values: "drop" },
      metrics: { accuracy: 0.95 },
      logs: [{ level: "info", message: "complete" }],
    };
    const get = vi.spyOn(apiClient, "get")
      .mockResolvedValueOnce({ data: { items: [job] } })
      .mockResolvedValueOnce({ data: job });

    expect(await listTrainingJobs()).toEqual([job]);
    expect(await getTrainingJob("job-1")).toEqual(job);
    expect(get).toHaveBeenNthCalledWith(1, "/training/jobs", { params: undefined });
    expect(get).toHaveBeenNthCalledWith(2, "/training/jobs/job-1");
  });
});
