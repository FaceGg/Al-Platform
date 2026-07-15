import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import { listWorkflowVersions, publishWorkflow, restoreWorkflowVersion } from "./workflowVersions";

describe("workflow version API", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("publishes the current workflow draft", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { version: 1 } });
    await publishWorkflow("wf-1");
    expect(post).toHaveBeenCalledWith("/workflows/wf-1/publish");
  });

  it("lists versions and restores a selected snapshot", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: { items: [{ version: 2 }] } });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { version: 2 } });
    expect(await listWorkflowVersions("wf-1")).toEqual([{ version: 2 }]);
    await restoreWorkflowVersion("wf-1", 2);
    expect(post).toHaveBeenCalledWith("/workflows/wf-1/versions/2/restore");
  });
});
