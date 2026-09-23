import apiClient from "./client";

export type ReturnBatchState = "pending" | "accepted" | "returned_for_changes";

export interface ReturnBatch {
  id: string;
  assignment_id: string;
  task_revision: number;
  state: ReturnBatchState | string;
  created_at: string | null;
  accepted_dataset_version_id?: string | null;
  operation_state?: string | null;
  validated_row_count?: number | null;
  task_id?: string | null;
  task_name?: string | null;
  annotator_subject_id?: string | null;
  annotator_name?: string | null;
  /** 原始待标注文件（任务数据集对应的数据制品名） */
  source_dataset_name?: string | null;
  /** 验收后导出保存到数据管理的数据制品名（未导出时为空） */
  saved_dataset_name?: string | null;
}

export interface ReturnBatchPage { items: ReturnBatch[]; total: number; next_cursor: string | null; }
export interface ReturnDiffRow { sample_id: string; source_values: Record<string, unknown>; label_values: Record<string, unknown>; }
export interface ReturnDiffPage { items: ReturnDiffRow[]; total: number; next_cursor: string | null; }

export async function listReturnBatches(projectId: string, cursor?: string, limit = 50): Promise<ReturnBatchPage> {
  const response = await apiClient.get(`/projects/${encodeURIComponent(projectId)}/annotation-return-batches`, { params: { cursor, limit } });
  return response.data as ReturnBatchPage;
}

export async function diffReturnBatch(returnBatchId: string, cursor?: string, limit = 50): Promise<ReturnDiffPage> {
  const response = await apiClient.get(`/annotation-return-batches/${encodeURIComponent(returnBatchId)}/diff`, { params: { cursor, limit } });
  return response.data as ReturnDiffPage;
}

export async function acceptReturnBatch(returnBatchId: string, taskRevision: number) {
  const response = await apiClient.post(`/annotation-return-batches/${encodeURIComponent(returnBatchId)}/accept`, { task_revision: taskRevision });
  return response.data as { dataset_version_id: string; status: string; version: number };
}

export async function returnReturnBatch(returnBatchId: string, payload: { task_revision: number; reason: string }) {
  const response = await apiClient.post(`/annotation-return-batches/${encodeURIComponent(returnBatchId)}/return`, payload);
  return response.data as { id: string; state: ReturnBatchState | string };
}

export interface ExportLabelColumn {
  machine_key: string;
  display_name: string;
  value_type: "int" | "float" | "string" | string;
  mapping?: Record<string, number>;
}

export interface ExportPreview {
  return_batch_id: string;
  task_id: string;
  task_name: string | null;
  row_count: number;
  columns: ExportLabelColumn[];
}

export interface ExportDatasetResult {
  dataset_id: string;
  name: string;
  dataset_version_id: string;
  version: number;
  row_count: number;
  label_mappings: Record<string, Record<string, number>>;
}

export async function exportReturnBatchPreview(returnBatchId: string): Promise<ExportPreview> {
  const response = await apiClient.get(`/annotation-return-batches/${encodeURIComponent(returnBatchId)}/export-preview`);
  return response.data as ExportPreview;
}

// Chinese label column names must be renamed to English identifiers before the
// accepted labels can be saved as a dataset; renames maps machine_key → new name.
export async function exportReturnBatchDataset(
  returnBatchId: string,
  name: string,
  renames: Record<string, string> = {},
): Promise<ExportDatasetResult> {
  const response = await apiClient.post(`/annotation-return-batches/${encodeURIComponent(returnBatchId)}/export-dataset`, { name, renames });
  return response.data as ExportDatasetResult;
}
