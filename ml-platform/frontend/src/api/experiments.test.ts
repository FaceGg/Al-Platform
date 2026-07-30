import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import {
  compareExperimentRuns,
  createExperiment,
  deleteExperiment,
  getExperiment,
  listExperimentRuns,
  listExperiments,
} from "./experiments";

describe("experiment tracking API", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("uses project-scoped experiment endpoints", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { id: "e1" } });
    const get = vi.spyOn(apiClient, "get")
      .mockResolvedValueOnce({ data: { items: [{ id: "e1" }] } })
      .mockResolvedValueOnce({ data: { id: "e1" } })
      .mockResolvedValueOnce({ data: { items: [{ run_id: "r1" }], total: 1 } });

    await createExperiment({ project_id: "p1", name: "Baseline", description: "Weld" });
    expect(await listExperiments("p1")).toEqual([{ id: "e1" }]);
    await getExperiment("e1");
    expect(await listExperimentRuns("e1", 20, 40)).toEqual({ items: [{ run_id: "r1" }], total: 1 });

    expect(post).toHaveBeenCalledWith("/experiments", {
      project_id: "p1", name: "Baseline", description: "Weld",
    });
    expect(get).toHaveBeenNthCalledWith(1, "/experiments", { params: { project_id: "p1" } });
    expect(get).toHaveBeenNthCalledWith(2, "/experiments/e1");
    expect(get).toHaveBeenNthCalledWith(3, "/experiments/e1/runs", {
      params: { limit: 20, offset: 40 },
    });
  });

  it("posts deterministic Run comparisons", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { run_ids: ["run-1", "run-2"], param_names: [], metric_names: [], runs: [] },
    });

    await compareExperimentRuns("experiment-1", ["run-1", "run-2"]);

    expect(post).toHaveBeenCalledWith("/experiments/experiment-1/compare", {
      run_ids: ["run-1", "run-2"],
    });
  });

  it("deletes a platform Experiment without constructing tracking URLs", async () => {
    const remove = vi.spyOn(apiClient, "delete").mockResolvedValue({ data: undefined });

    await deleteExperiment("experiment-1");

    expect(remove).toHaveBeenCalledWith("/experiments/experiment-1");
  });
});
