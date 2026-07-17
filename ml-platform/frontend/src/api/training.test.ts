import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import {
  createTensorBoardSession,
  createTrainingJob,
  getTrainingJob,
  listTrainingCheckpoints,
  listTrainingJobs,
  resumeTrainingJob,
  stopTrainingJob,
} from "./training";

describe("training API", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("creates training from a dataset artifact", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { job_id: "job-1", status: "queued" },
    });

    await createTrainingJob({
      project_id: "project-1",
      experiment_id: "experiment-1",
      dataset_artifact_id: "artifact-1",
      name: "weld-quality",
      target_column: "quality",
      task: "classification",
      total_epochs: 20,
    });

    expect(post).toHaveBeenCalledWith("/training/run", {
      project_id: "project-1",
      experiment_id: "experiment-1",
      dataset_artifact_id: "artifact-1",
      name: "weld-quality",
      target_column: "quality",
      task: "classification",
      total_epochs: 20,
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

  it("uses job-scoped checkpoint and control endpoints", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({
      data: { checkpoints: [{ path: "checkpoints/best.joblib", uri: "mlflow-artifacts:/best" }] },
    });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: {} });

    expect(await listTrainingCheckpoints("job-1")).toHaveLength(1);
    await stopTrainingJob("job-1");
    await resumeTrainingJob("job-1", "checkpoints/best.joblib");
    await createTensorBoardSession("job-1");

    expect(get).toHaveBeenCalledWith("/training/jobs/job-1/checkpoints");
    expect(post).toHaveBeenNthCalledWith(1, "/training/jobs/job-1/stop");
    expect(post).toHaveBeenNthCalledWith(2, "/training/jobs/job-1/resume", {
      checkpoint_path: "checkpoints/best.joblib",
    });
    expect(post).toHaveBeenNthCalledWith(3, "/training/jobs/job-1/tensorboard-session");
  });
});
