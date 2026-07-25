import GBK from "gbk.js";

export type WorkflowExportFormat = "csv" | "json" | "text";

export interface BrowserExportOptions {
  separator?: unknown;
  includeHeader?: unknown;
  encoding?: unknown;
  textSummary?: boolean;
}

export interface BrowserWritableFile {
  write(data: Blob): Promise<void>;
  close(): Promise<void>;
}

export interface BrowserDirectoryHandle {
  name: string;
  getFileHandle(name: string, options: { create: boolean }): Promise<{
    createWritable(): Promise<BrowserWritableFile>;
  }>;
}

export type WorkflowExportOutcome = "saved" | "downloaded" | "skipped";

export interface CompletedWorkflowExportInput {
  operatorId: string;
  nodeId: string;
  params: Record<string, any>;
  result: unknown;
  directory?: BrowserDirectoryHandle;
  fileSystemAccessAvailable?: boolean;
}

const EXPORT_OPERATOR_IDS = new Set(["csv_export", "write_csv", "write_as_text"]);

export function isWorkflowExportOperator(operatorId?: string): boolean {
  return Boolean(operatorId && EXPORT_OPERATOR_IDS.has(operatorId));
}

export function exportFormat(operatorId: string, params: Record<string, any>): WorkflowExportFormat {
  if (operatorId === "csv_export" || operatorId === "write_csv") return "csv";
  const value = String(params.format || "text");
  return value === "json" || value === "csv" ? value : "text";
}

function exportExtension(format: WorkflowExportFormat): string {
  return format === "text" ? "txt" : format;
}

function fileStem(value: unknown, fallback: string): string {
  const raw = String(value || "").trim().replace(/[\\/:*?"<>|]+/g, "_");
  const stem = raw.replace(/\.[^.]+$/, "").trim();
  return stem || fallback;
}

export function buildExportFilename(
  operatorId: string,
  nodeId: string,
  params: Record<string, any>,
): string {
  const format = exportFormat(operatorId, params);
  const stem = fileStem(params.file_name, `${operatorId}_${nodeId}`);
  return `${stem}.${exportExtension(format)}`;
}

function csvSeparator(value: unknown): string {
  const separator = value == null ? "," : String(value);
  return separator.replace(/\\t/g, "\t") || ",";
}

function quoteCsv(value: unknown, separator: string): string {
  const text = value == null ? "" : String(value);
  return text.includes(separator) || /["\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function asRows(value: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(value)) {
    return value.map((item) => (
      item && typeof item === "object" && !Array.isArray(item)
        ? item as Record<string, unknown>
        : { value: item }
    ));
  }
  if (value && typeof value === "object") return [value as Record<string, unknown>];
  return [{ value }];
}

function toCsv(value: unknown, separator: string, includeHeader: boolean): string {
  const rows = asRows(value);
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  if (!columns.length) return "";
  return [
    ...(includeHeader ? [columns.map((column) => quoteCsv(column, separator)).join(separator)] : []),
    ...rows.map((row) => columns.map((column) => quoteCsv(row[column], separator)).join(separator)),
  ].join("\r\n");
}

function textSummary(value: unknown): string {
  const rows = asRows(value);
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  if (!rows.length || !columns.length) return "(empty data)";

  const preview = rows.slice(0, 10).map((row) => (
    columns.map((column) => row[column] == null ? "" : String(row[column])).join("\t")
  ));
  return [
    `Rows: ${rows.length}, Columns: [${columns.map((column) => `'${column}'`).join(", ")}]`,
    columns.join("\t"),
    ...preview,
  ].join("\n");
}

function browserTextEncoding(encoding: unknown): "utf-8" | "gbk" {
  return String(encoding || "utf-8").toLowerCase() === "gbk" ? "gbk" : "utf-8";
}

function csvBlobParts(content: string, encoding: "utf-8" | "gbk"): BlobPart[] {
  if (encoding === "gbk") return [new Uint8Array(GBK.encode(content))];
  return ["\uFEFF", content];
}

export function buildExportBlob(
  value: unknown,
  format: WorkflowExportFormat,
  options: BrowserExportOptions = {},
): Blob {
  if (format === "csv") {
    const separator = csvSeparator(options.separator);
    const includeHeader = options.includeHeader === undefined || Boolean(options.includeHeader);
    const encoding = browserTextEncoding(options.encoding);
    return new Blob(csvBlobParts(toCsv(value, separator, includeHeader), encoding), {
      type: `text/csv;charset=${encoding}`,
    });
  }
  if (format === "json") {
    return new Blob([JSON.stringify(value, null, 2)], { type: "application/json;charset=utf-8" });
  }
  const text = options.textSummary
    ? textSummary(value)
    : typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return new Blob([text], { type: "text/plain;charset=utf-8" });
}

function isResultRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function completedExportValue(result: unknown): unknown {
  if (!isResultRecord(result)) return result;
  const outputs = isResultRecord(result.outputs) ? result.outputs : result;
  return Object.prototype.hasOwnProperty.call(outputs, "data") ? outputs.data : outputs;
}

/** Returns false after the first completion event for a run/node pair. */
export function markRunNodeExported(completed: Set<string>, runId: string, nodeId: string): boolean {
  const key = `${runId}:${nodeId}`;
  if (completed.has(key)) return false;
  completed.add(key);
  return true;
}

export async function saveWorkflowExport(
  directory: BrowserDirectoryHandle,
  filename: string,
  blob: Blob,
): Promise<void> {
  const file = await directory.getFileHandle(filename, { create: true });
  const writable = await file.createWritable();
  await writable.write(blob);
  await writable.close();
}

export function triggerBrowserDownload(blob: Blob, filename: string): void {
  if (typeof document === "undefined" || typeof URL.createObjectURL !== "function") return;
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(href);
}

export async function exportCompletedWorkflowNode({
  operatorId,
  nodeId,
  params,
  result,
  directory,
  fileSystemAccessAvailable = typeof window !== "undefined" &&
    typeof (window as Window & { showDirectoryPicker?: unknown }).showDirectoryPicker === "function",
}: CompletedWorkflowExportInput): Promise<WorkflowExportOutcome> {
  if (!isWorkflowExportOperator(operatorId)) return "skipped";

  const format = exportFormat(operatorId, params);
  const filename = buildExportFilename(operatorId, nodeId, params);
  const blob = buildExportBlob(completedExportValue(result), format, {
    separator: params.separator,
    includeHeader: params.include_header,
    encoding: params.encoding,
    textSummary: operatorId === "write_as_text",
  });
  if (fileSystemAccessAvailable) {
    if (!directory) return "skipped";
    await saveWorkflowExport(directory, filename, blob);
    return "saved";
  }

  triggerBrowserDownload(blob, filename);
  return "downloaded";
}
