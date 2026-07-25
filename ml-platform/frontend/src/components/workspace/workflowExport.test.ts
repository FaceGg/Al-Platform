import { describe, expect, it, vi } from "vitest";
import * as workflowExport from "./workflowExport";

async function readBlobText(blob: Blob): Promise<string> {
  if (typeof blob.text === "function") return blob.text();

  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error || new Error("Unable to read export blob"));
    reader.readAsText(blob, "utf-8");
  });
}

async function readBlobBytes(blob: Blob): Promise<number[]> {
  if (typeof blob.arrayBuffer === "function") return [...new Uint8Array(await blob.arrayBuffer())];

  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve([...new Uint8Array(reader.result as ArrayBuffer)]);
    reader.onerror = () => reject(reader.error || new Error("Unable to read export blob"));
    reader.readAsArrayBuffer(blob);
  });
}

describe("workflow export serialization", () => {
  it("uses a deterministic CSV filename when no name is supplied", () => {
    expect(workflowExport.buildExportFilename("csv_export", "node-1", { file_name: "" })).toBe(
      "csv_export_node-1.csv",
    );
  });

  it("serializes tabular data as a CSV Blob", () => {
    const blob = workflowExport.buildExportBlob([{ id: 1, value: "ok" }], "csv");

    expect(blob.type).toContain("text/csv");
  });

  it("honors browser CSV separator, header, and GBK encoding options", async () => {
    const buildExportBlob = workflowExport.buildExportBlob as (...args: any[]) => Blob;
    const blob = buildExportBlob([
      { id: 1, status: "\u710a\u63a5" },
      { id: 2, status: "ok" },
    ], "csv", {
      separator: ";",
      includeHeader: false,
      encoding: "gbk",
    });

    expect(blob.type).toContain("text/csv;charset=gbk");
    expect(await readBlobBytes(blob)).toEqual([
      0x31, 0x3b, 0xba, 0xb8, 0xbd, 0xd3, 0x0d, 0x0a, 0x32, 0x3b, 0x6f, 0x6b,
    ]);
  });

  it("uses a backend-style rows summary for text-mode WriteAsText exports", async () => {
    const buildExportBlob = workflowExport.buildExportBlob as (...args: any[]) => Blob;
    const blob = buildExportBlob([
      { id: 1, status: "ok" },
      { id: 2, status: "failed" },
    ], "text", { textSummary: true });

    expect((await readBlobText(blob)).startsWith("Rows: 2, Columns: ['id', 'status']\n")).toBe(true);
  });

  it("writes a completed export node's output into the chosen directory", async () => {
    const exportCompletedWorkflowNode = (workflowExport as any).exportCompletedWorkflowNode;
    expect(typeof exportCompletedWorkflowNode).toBe("function");

    const write = vi.fn().mockResolvedValue(undefined);
    const close = vi.fn().mockResolvedValue(undefined);
    const createWritable = vi.fn().mockResolvedValue({ write, close });
    const getFileHandle = vi.fn().mockResolvedValue({ createWritable });

    await expect(exportCompletedWorkflowNode({
      operatorId: "write_as_text",
      nodeId: "export-1",
      params: { format: "json", file_name: "quality-report" },
      result: { outputs: { data: [{ id: 1, status: "ok" }] } },
      directory: { name: "exports", getFileHandle },
      fileSystemAccessAvailable: true,
    })).resolves.toBe("saved");

    expect(getFileHandle).toHaveBeenCalledWith("quality-report.json", { create: true });
    expect(createWritable).toHaveBeenCalledOnce();
    expect(write).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
    expect((write.mock.calls[0][0] as Blob).type).toContain("application/json");
  });

  it("passes CSV options through the completed export path", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    const close = vi.fn().mockResolvedValue(undefined);
    const createWritable = vi.fn().mockResolvedValue({ write, close });
    const getFileHandle = vi.fn().mockResolvedValue({ createWritable });

    await expect(workflowExport.exportCompletedWorkflowNode({
      operatorId: "csv_export",
      nodeId: "export-1",
      params: { separator: ";", include_header: false, encoding: "gbk" },
      result: { outputs: { data: [{ id: 1, status: "\u710a\u63a5" }] } },
      directory: { name: "exports", getFileHandle },
      fileSystemAccessAvailable: true,
    })).resolves.toBe("saved");

    expect(await readBlobBytes(write.mock.calls[0][0] as Blob)).toEqual([
      0x31, 0x3b, 0xba, 0xb8, 0xbd, 0xd3,
    ]);
  });

  it("does not fall back to a browser download while the file system API is available", async () => {
    const exportCompletedWorkflowNode = (workflowExport as any).exportCompletedWorkflowNode;
    expect(typeof exportCompletedWorkflowNode).toBe("function");

    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    await expect(exportCompletedWorkflowNode({
      operatorId: "csv_export",
      nodeId: "export-1",
      params: {},
      result: { data: [{ id: 1 }] },
      fileSystemAccessAvailable: true,
    })).resolves.toBe("skipped");

    expect(click).not.toHaveBeenCalled();
    click.mockRestore();
  });

  it("falls back to a browser download only when the file system API is unavailable", async () => {
    const exportCompletedWorkflowNode = (workflowExport as any).exportCompletedWorkflowNode;
    expect(typeof exportCompletedWorkflowNode).toBe("function");

    const createObjectURL = vi.fn().mockReturnValue("blob:workflow-export");
    const revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
    const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });

    try {
      await expect(exportCompletedWorkflowNode({
        operatorId: "csv_export",
        nodeId: "export-1",
        params: {},
        result: { data: [{ id: 1 }] },
        fileSystemAccessAvailable: false,
      })).resolves.toBe("downloaded");

      expect(click).toHaveBeenCalledOnce();
      expect(createObjectURL).toHaveBeenCalledOnce();
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:workflow-export");
    } finally {
      click.mockRestore();
      if (originalCreateObjectURL) Object.defineProperty(URL, "createObjectURL", originalCreateObjectURL);
      else delete (URL as any).createObjectURL;
      if (originalRevokeObjectURL) Object.defineProperty(URL, "revokeObjectURL", originalRevokeObjectURL);
      else delete (URL as any).revokeObjectURL;
    }
  });

  it("deduplicates completed export attempts by run and node", () => {
    const markRunNodeExported = (workflowExport as any).markRunNodeExported;
    expect(typeof markRunNodeExported).toBe("function");

    const completed = new Set<string>();
    expect(markRunNodeExported(completed, "run-1", "export-1")).toBe(true);
    expect(markRunNodeExported(completed, "run-1", "export-1")).toBe(false);
    expect(markRunNodeExported(completed, "run-2", "export-1")).toBe(true);
  });
});
