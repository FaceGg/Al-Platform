import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import { acceptReturnBatch, diffReturnBatch, listReturnBatches, returnReturnBatch } from "./annotationReturns";

vi.mock("./client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));

const client = vi.mocked(apiClient);

describe("annotationReturns API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists project batches with a stable cursor", async () => {
    client.get.mockResolvedValue({ data: { items: [], total: 0, next_cursor: null } });
    await listReturnBatches("project-1", "cursor-1", 25);
    expect(client.get).toHaveBeenCalledWith("/projects/project-1/annotation-return-batches", { params: { cursor: "cursor-1", limit: 25 } });
  });

  it("posts an explicit review revision and reason", async () => {
    client.post.mockResolvedValue({ data: { state: "returned_for_changes" } });
    await returnReturnBatch("batch-1", { task_revision: 4, reason: "请补齐必填值" });
    expect(client.post).toHaveBeenCalledWith("/annotation-return-batches/batch-1/return", { task_revision: 4, reason: "请补齐必填值" });
  });

  it("loads a batch diff and accepts a matching revision", async () => {
    client.get.mockResolvedValue({ data: { items: [], total: 0, next_cursor: null } });
    client.post.mockResolvedValue({ data: { status: "ready" } });
    await diffReturnBatch("batch-1", undefined, 50);
    await acceptReturnBatch("batch-1", 4);
    expect(client.get).toHaveBeenCalledWith("/annotation-return-batches/batch-1/diff", { params: { cursor: undefined, limit: 50 } });
    expect(client.post).toHaveBeenCalledWith("/annotation-return-batches/batch-1/accept", { task_revision: 4 });
  });
});
