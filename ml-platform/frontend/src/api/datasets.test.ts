import { beforeEach, describe, expect, it, vi } from "vitest";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("./client", () => ({ default: { get } }));

import { downloadDatasetArtifact, listDatasets } from "./datasets";

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

  it("downloads the stored artifact bytes with the server filename", async () => {
    const blob = new Blob(["cvei,cvev,cver,cvep\n1,2,3,4\n"], { type: "text/csv" });
    get.mockResolvedValue({
      data: blob,
      headers: { "content-disposition": "attachment; filename*=utf-8''weld-export.csv" },
    });
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:dataset");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    await downloadDatasetArtifact("artifact-1", "fallback.csv");

    expect(get).toHaveBeenCalledWith("/datasets/artifact-1/download", { responseType: "blob" });
    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:dataset");
    click.mockRestore();
    createObjectURL.mockRestore();
    revokeObjectURL.mockRestore();
  });
});
