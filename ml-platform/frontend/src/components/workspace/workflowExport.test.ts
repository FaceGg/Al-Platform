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

  it("does not download a completed export payload automatically", async () => {
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

  it("deduplicates completed export attempts by run and node", () => {
    const markRunNodeExported = (workflowExport as any).markRunNodeExported;
    expect(typeof markRunNodeExported).toBe("function");

    const completed = new Set<string>();
    expect(markRunNodeExported(completed, "run-1", "export-1")).toBe(true);
    expect(markRunNodeExported(completed, "run-1", "export-1")).toBe(false);
    expect(markRunNodeExported(completed, "run-2", "export-1")).toBe(true);
  });
});
