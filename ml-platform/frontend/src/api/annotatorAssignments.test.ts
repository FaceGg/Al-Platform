import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import { createAssignments, listAnnotatorSubjects } from "./annotatorAssignments";

vi.mock("./client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));

const client = vi.mocked(apiClient);

describe("annotatorAssignments API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists annotators without accepting a client project id", async () => {
    client.get.mockResolvedValue({ data: { items: [{ id: "subject-1", username: "reviewer" }] } });
    await listAnnotatorSubjects("rev");
    expect(client.get).toHaveBeenCalledWith("/annotators", { params: { q: "rev" } });
  });

  it("sends the selected subjects and fixed sample scope", async () => {
    client.post.mockResolvedValue({ data: { items: [{ id: "assignment-1" }] } });
    await createAssignments("task-1", { annotator_ids: ["subject-1"], sample_scope: { kind: "ids", sample_ids: ["s-1"] }, due_at: undefined });
    expect(client.post).toHaveBeenCalledWith("/annotation-tasks/task-1/assignments", { annotator_ids: ["subject-1"], sample_scope: { kind: "ids", sample_ids: ["s-1"] }, due_at: undefined });
  });
});
