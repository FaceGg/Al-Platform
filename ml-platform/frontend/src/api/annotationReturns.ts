import apiClient from "./client";

export type ReturnBatchState = "pending" | "accepted" | "returned_for_changes";

export interface ReturnBatch {
  id: string;
  assignment_id: string;
  task_revision: number;
  state: ReturnBatchState | string;
  created_at: string | null;
  accepted_dataset_version_id?: string | null;
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
