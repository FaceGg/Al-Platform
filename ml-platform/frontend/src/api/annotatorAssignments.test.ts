import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import {
  createAssignments,
  grantAnnotatorProject,
  listAnnotatorProjectGrants,
  listAnnotatorSubjects,
  revokeAnnotatorProject,
} from "./annotatorAssignments";

vi.mock("./client", () => ({ default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));

const client = vi.mocked(apiClient);

describe("annotatorAssignments API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists annotators with an optional search query", async () => {
    client.get.mockResolvedValue({ data: { items: [{ id: "subject-1", username: "reviewer" }] } });
    await listAnnotatorSubjects("rev");
    expect(client.get).toHaveBeenCalledWith("/annotators", { params: { q: "rev", project_id: undefined } });
  });

  it("filters annotators to the project's active grantees when a project id is given", async () => {
    client.get.mockResolvedValue({ data: { items: [] } });
    await listAnnotatorSubjects("", "project-1");
    expect(client.get).toHaveBeenCalledWith("/annotators", { params: { q: undefined, project_id: "project-1" } });
  });

  it("lists an annotator's project grants", async () => {
    client.get.mockResolvedValue({ data: { items: [{ project_id: "project-1", status: "active" }] } });
    const grants = await listAnnotatorProjectGrants("subject-1");
    expect(client.get).toHaveBeenCalledWith("/admin/annotators/subject-1/grants");
    expect(grants).toEqual([{ project_id: "project-1", status: "active" }]);
  });

  it("grants and revokes project access for an annotator", async () => {
    client.post.mockResolvedValue({ data: {} });
    client.delete.mockResolvedValue({ data: {} });
    await grantAnnotatorProject("project-1", "subject-1");
    await revokeAnnotatorProject("project-2", "subject-1");
    expect(client.post).toHaveBeenCalledWith("/internal/projects/project-1/annotators/subject-1/grant");
    expect(client.delete).toHaveBeenCalledWith("/internal/projects/project-2/annotators/subject-1/grant");
  });

  it("sends the selected subjects and fixed sample scope", async () => {
    client.post.mockResolvedValue({ data: { items: [{ id: "assignment-1" }] } });
    await createAssignments("task-1", { annotator_ids: ["subject-1"], sample_scope: { kind: "ids", sample_ids: ["s-1"] }, due_at: undefined });
    expect(client.post).toHaveBeenCalledWith(
      "/annotation-tasks/task-1/assignments",
      { annotator_ids: ["subject-1"], sample_scope: { kind: "ids", sample_ids: ["s-1"] }, due_at: undefined },
      { headers: { "X-Request-ID": expect.any(String), "Idempotency-Key": expect.any(String) } },
    );
  });

  it("supports server-owned frozen task scopes without sending sample ids", async () => {
    client.post.mockResolvedValue({ data: { items: [{ id: "assignment-1" }] } });
    await createAssignments("task-1", {
      annotator_ids: ["subject-1"],
      sample_scope: { kind: "frozen_task_scope" },
    });
    expect(client.post).toHaveBeenCalledWith(
      "/annotation-tasks/task-1/assignments",
      { annotator_ids: ["subject-1"], sample_scope: { kind: "frozen_task_scope" }, due_at: undefined },
      { headers: { "X-Request-ID": expect.any(String), "Idempotency-Key": expect.any(String) } },
    );
  });
});
