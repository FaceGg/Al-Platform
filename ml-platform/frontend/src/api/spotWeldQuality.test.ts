import { beforeEach, describe, expect, it, vi } from "vitest";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("./client", () => ({ default: { get, post } }));

import {
  createQualityRun,
  getQualityModel,
  getQualitySample,
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
    // 按 URL 定向 mock，避免 Once 队列对调用顺序的脆弱耦合
    get.mockImplementation(async (url: string, config?: { params?: Record<string, unknown> }) => {
      if (url === "/projects/project-1/spot-weld/runs") {
        return {
          data: {
            items: [{ id: "run-1" }],
            total: 1,
            limit: config?.params?.limit ?? 200,
            offset: config?.params?.offset ?? 0,
          },
        };
      }
      if (url === "/projects/project-1/spot-weld/runs/run-1/samples") {
        return { data: { items: [{ id: "sample-1" }] } };
      }
      if (url === "/projects/project-1/spot-weld/runs/run-1/samples/sample-1") {
        return { data: { id: "sample-1", waveforms: {} } };
      }
      throw new Error(`unexpected GET ${url}`);
    });

    await expect(listQualityRuns("project-1")).resolves.toEqual({
      items: [{ id: "run-1" }],
      total: 1,
    });
    await expect(listQualitySamples("project-1", "run-1", { review_status: "pending_review" }))
      .resolves.toEqual([{ id: "sample-1" }]);
    await expect(getQualitySample("project-1", "run-1", "sample-1"))
      .resolves.toEqual({ id: "sample-1", waveforms: {} });

    expect(get).toHaveBeenNthCalledWith(1, "/projects/project-1/spot-weld/runs");
    await expect(listQualityRuns("project-1", { limit: 20, offset: 20 })).resolves.toEqual({
      items: [{ id: "run-1" }],
      total: 1,
    });
    expect(get).toHaveBeenLastCalledWith("/projects/project-1/spot-weld/runs", {
      params: { limit: 20, offset: 20 },
    });
  });

  it("lists all accessible quality runs when no project is selected", async () => {
    get.mockResolvedValueOnce({ data: { items: [{ id: "run-1" }, { id: "run-2" }], total: 2 } });

    await expect(listQualityRuns()).resolves.toEqual({
      items: [{ id: "run-1" }, { id: "run-2" }],
      total: 2,
    });
    expect(get).toHaveBeenCalledWith("/spot-weld/runs");
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
    const file = new File(["wld1c"], "report.csv", { type: "text/csv" });

    await expect(uploadQualityDataset("project-1", file)).resolves.toMatchObject({ artifact_id: "artifact-1" });
    await expect(validateQualityDataset("project-1", "artifact-1")).resolves.toMatchObject({ valid_rows: 12 });

    expect(post.mock.calls[0][0]).toBe("/projects/project-1/datasets/upload");
    expect(post.mock.calls[0][1]).toBeInstanceOf(FormData);
    expect(post).toHaveBeenNthCalledWith(
      2,
      "/projects/project-1/spot-weld/validate",
      { dataset_artifact_id: "artifact-1", field_mapping: {} },
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

    expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs",
      {
        dataset_artifact_id: "artifact-1",
        algorithm_ids: ["random_forest"],
        search_method: "multi_fidelity",
        max_trials: 20,
        time_budget: 600,
      },
      { headers: { "X-Request-ID": expect.any(String), "Idempotency-Key": expect.any(String) } },
    );
    expect(post.mock.calls[0][1]).not.toHaveProperty("candidate_ids");
  });

  it("loads generated models only through project-scoped routes", async () => {
    get.mockResolvedValueOnce({ data: { items: [{ id: "model-1", name: "quality", params: {} }] } });
    get.mockResolvedValueOnce({ data: { id: "model-1", name: "quality", params: {} } });

    await expect(listQualityModels("project-1")).resolves.toEqual([{ id: "model-1", name: "quality", params: {} }]);
    await expect(getQualityModel("project-1", "run-1")).resolves.toEqual({ id: "model-1", name: "quality", params: {} });

    expect(get).toHaveBeenNthCalledWith(1, "/projects/project-1/spot-weld/models");
    expect(get).toHaveBeenNthCalledWith(2, "/projects/project-1/spot-weld/runs/run-1/quality-model");
  });
});
