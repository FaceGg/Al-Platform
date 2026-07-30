import { beforeEach, describe, expect, it, vi } from "vitest";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("./client", () => ({ default: { get, post } }));

import {
  getQualitySample,
  listQualityRuns,
  listQualitySamples,
  reviewQualityLabel,
  submitQualityLabel,
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
});
