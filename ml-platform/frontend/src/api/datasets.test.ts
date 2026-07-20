import { beforeEach, describe, expect, it, vi } from "vitest";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("./client", () => ({ default: { get } }));

import { listDatasets } from "./datasets";

describe("listDatasets", () => {
  beforeEach(() => get.mockReset());

  it("loads all owned datasets when no project filter is provided", async () => {
    get.mockResolvedValue({ data: { items: [], total: 0 } });

    await listDatasets();

    expect(get).toHaveBeenCalledWith("/datasets");
  });

  it("uses the project query parameter when filtering datasets", async () => {
    get.mockResolvedValue({ data: { items: [], total: 0 } });

    await listDatasets("project-1");

    expect(get).toHaveBeenCalledWith("/datasets?project_id=project-1");
  });
});
