import { beforeEach, describe, expect, it, vi } from "vitest";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("./client", () => ({ default: { get, post } }));

import {
  createQualityRun,
  createQualityDemoDataset,
  getQualityModel,
  getQualitySample,
  getQualityWarningSummary,
  listQualityModels,
  listQualityRuns,
  listQualitySamples,
  reviewQualityLabel,
  submitQualityLabel,
  uploadQualityDataset,
  validateQualityDataset,
} from "./spotWeldQuality";

describe("spot weld quality API", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it("keeps every read project and run scoped", async () => {
    get.mockResolvedValueOnce({ data: { items: [{ id: "run-1" }] } });
    get.mockResolvedValueOnce({ data: { items: [{ id: "sample-1" }] } });
    get.mockResolvedValueOnce({ data: { id: "sample-1", waveforms: {} } });

    await expect(listQualityRuns("project-1")).resolves.toEqual([{ id: "run-1" }]);
    await expect(listQualitySamples("project-1", "run-1", { review_status: "pending_review" }))
      .resolves.toEqual([{ id: "sample-1" }]);
    await expect(getQualitySample("project-1", "run-1", "sample-1"))
      .resolves.toEqual({ id: "sample-1", waveforms: {} });

    expect(get).toHaveBeenNthCalledWith(1, "/projects/project-1/spot-weld/runs");
    expect(get).toHaveBeenNthCalledWith(2, "/projects/project-1/spot-weld/runs/run-1/samples", {
      params: { review_status: "pending_review" },
    });
    expect(get).toHaveBeenNthCalledWith(3, "/projects/project-1/spot-weld/runs/run-1/samples/sample-1");
  });

  it("posts label and review payloads to the selected sample", async () => {
    post.mockResolvedValue({ data: { id: "revision-1" } });

    await submitQualityLabel("project-1", "run-1", "sample-1", {
      label: "power_fluctuation",
      note: "waveform confirmed",
    });
    await reviewQualityLabel("project-1", "run-1", "sample-1", {
      decision: "approved",
      comment: "verified",
    });

    expect(post).toHaveBeenNthCalledWith(
      1,
      "/projects/project-1/spot-weld/runs/run-1/samples/sample-1/labels",
      { label: "power_fluctuation", note: "waveform confirmed" },
    );
    expect(post).toHaveBeenNthCalledWith(
      2,
      "/projects/project-1/spot-weld/runs/run-1/samples/sample-1/review",
      { decision: "approved", comment: "verified" },
    );
  });

  it("uploads, validates, and starts report-compatible quality data", async () => {
    post.mockResolvedValueOnce({ data: { artifact_id: "artifact-1" } });
    post.mockResolvedValueOnce({ data: { valid_rows: 12, errors: [] } });
    post.mockResolvedValueOnce({ data: { artifact_id: "demo-artifact", row_count: 60 } });
    const file = new File(["wld1c"], "report.csv", { type: "text/csv" });

    await expect(uploadQualityDataset("project-1", file)).resolves.toMatchObject({ artifact_id: "artifact-1" });
    await expect(validateQualityDataset("project-1", "artifact-1")).resolves.toMatchObject({ valid_rows: 12 });
    await expect(createQualityDemoDataset("project-1")).resolves.toMatchObject({ artifact_id: "demo-artifact" });

    expect(post.mock.calls[0][0]).toBe("/projects/project-1/datasets/upload");
    expect(post.mock.calls[0][1]).toBeInstanceOf(FormData);
    expect(post).toHaveBeenNthCalledWith(
      2,
      "/projects/project-1/spot-weld/validate",
      { dataset_artifact_id: "artifact-1", field_mapping: {} },
    );
    expect(post).toHaveBeenNthCalledWith(
      3,
      "/projects/project-1/spot-weld/demo-dataset",
      { row_count: 60 },
    );
  });

  it("creates quality runs with the shared Optuna search contract", async () => {
    post.mockResolvedValueOnce({ data: { id: "run-1", status: "queued" } });

    await createQualityRun("project-1", {
      dataset_artifact_id: "artifact-1",
      algorithm_ids: ["random_forest"],
      search_method: "multi_fidelity",
      max_trials: 20,
      time_budget: 600,
    });

    expect(post).toHaveBeenCalledWith("/projects/project-1/spot-weld/runs", {
      dataset_artifact_id: "artifact-1",
      algorithm_ids: ["random_forest"],
      search_method: "multi_fidelity",
      max_trials: 20,
      time_budget: 600,
    });
    expect(post.mock.calls[0][1]).not.toHaveProperty("candidate_ids");
  });

  it("loads generated models and warning summaries only through project-scoped routes", async () => {
    get.mockResolvedValueOnce({ data: { items: [{ id: "model-1", name: "quality", params: {} }] } });
    get.mockResolvedValueOnce({ data: { id: "model-1", name: "quality", params: {} } });
    get.mockResolvedValueOnce({ data: { counts: { critical: 1, warning: 0, notice: 0, none: 4 }, items: [{ id: "sample-1", run_id: "run-1" }] } });

    await expect(listQualityModels("project-1")).resolves.toEqual([{ id: "model-1", name: "quality", params: {} }]);
    await expect(getQualityModel("project-1", "run-1")).resolves.toEqual({ id: "model-1", name: "quality", params: {} });
    await expect(getQualityWarningSummary("project-1")).resolves.toMatchObject({ counts: { critical: 1 }, items: [{ id: "sample-1", run_id: "run-1" }] });

    expect(get).toHaveBeenNthCalledWith(1, "/projects/project-1/spot-weld/models");
    expect(get).toHaveBeenNthCalledWith(2, "/projects/project-1/spot-weld/runs/run-1/quality-model");
    expect(get).toHaveBeenNthCalledWith(3, "/projects/project-1/spot-weld/warnings");
  });
});
