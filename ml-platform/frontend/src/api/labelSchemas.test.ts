import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import { createLabelSchema } from "./labelSchemas";

vi.mock("./client", () => ({ default: { post: vi.fn() } }));

const client = vi.mocked(apiClient);

describe("labelSchemas API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("persists enum and range constraints and strips editor-only fields", async () => {
    client.post.mockResolvedValue({ data: { id: "schema-1", project_id: "project-1", name: "labels", version: 1 } });
    await createLabelSchema("project-1", "labels", [
      { machine_key: "grade", display_name: "等级", value_type: "int", required: true, enum_values: [0, 1], constraint_mode: "enum", isDefault: true },
      { machine_key: "score", display_name: "分数", value_type: "float", required: true, min_value: 0, max_value: 1, constraint_mode: "range", instruction: "0 到 1" },
    ]);
    expect(client.post).toHaveBeenCalledWith("/annotations/label-schemas", {
      project_id: "project-1",
      name: "labels",
      purpose: "annotation",
      columns: [
        { machine_key: "grade", display_name: "等级", value_type: "int", required: true, enum_values: [0, 1] },
        { machine_key: "score", display_name: "分数", value_type: "float", required: true, min_value: 0, max_value: 1, instruction: "0 到 1" },
      ],
    });
  });
});
