import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import { listProjectModelArtifacts } from "./models";

describe("models client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("lists only the project-scoped model artifact endpoint", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({
      data: { items: [{ id: "artifact-1", name: "model.joblib", type: "model" }] },
    });

    await expect(listProjectModelArtifacts("project/1")).resolves.toEqual([
      { id: "artifact-1", name: "model.joblib", type: "model" },
    ]);
    expect(get).toHaveBeenCalledWith("/projects/project%2F1/models");
  });
});
