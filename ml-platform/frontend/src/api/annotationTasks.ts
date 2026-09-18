import apiClient from "./client";

export type AnnotationTask = {
  id: string;
  project_id: string;
  name?: string;
  completion_criteria?: string;
  due_at?: string | null;
  mode: "manual" | "automatic";
  status: string;
  task_revision: number;
  sample_scope: Record<string, unknown>;
  task_snapshot?: Record<string, any>;
  preview?: AnnotationPreview | null;
  created_at?: string | null;
};

export type GenericTaskCreatePayload = {
  project_id: string;
  dataset_version_id: string;
  label_schema_id?: string;
  model_version_id?: string;
  name?: string;
  mode: "manual" | "automatic";
  sample_scope: { kind: "all" | "ids" | "filter"; sample_ids?: string[]; filters?: Record<string, unknown> };
  label_snapshot?: Record<string, unknown>;
  visible_columns: string[];
  instructions: string;
  completion_criteria?: string;
  due_at?: string | null;
  configuration: Record<string, unknown>;
};

export type GenericTaskConfigurationPayload = {
  task_revision: number;
  name?: string;
  visible_columns: string[];
  instructions: string;
  completion_criteria?: string;
  due_at?: string | null;
  configuration: Record<string, unknown>;
};

export type AnnotationPreview = {
  id: string;
  operation_id?: string | null;
  task_revision: number;
  status: string;
  progress?: number;
  summary?: Record<string, unknown>;
  strategy_summary?: Record<string, unknown>;
  error_code?: string | null;
  error?: { code?: string | null; message?: string | null } | null;
};

export type AnnotationOperation = {
  id: string;
  resource_type: "annotation_preview" | "annotation_execution" | string;
  task_id: string;
  preview_id?: string | null;
  state: string;
  stage: string;
  progress: number;
  attempt: number;
  error_code?: string | null;
  checksum?: string | null;
  result_summary?: Record<string, unknown>;
  created_at?: string | null;
};

export async function listAnnotationTasks(projectId: string, limit = 50, cursor?: string) {
  const response = await apiClient.get("/annotation-tasks", { params: { project_id: projectId, limit, cursor } });
  return response.data as { items: AnnotationTask[]; total: number; next_cursor: string | null };
}

export async function createGenericAnnotationTask(payload: GenericTaskCreatePayload, idempotencyKey: string) {
  // Automatic annotation is still an annotation task. AutoML training has a
  // separate training contract and must not be selected by this helper.
  const response = await apiClient.post("/annotation-tasks", payload, {
    headers: { "X-Request-ID": crypto.randomUUID(), "Idempotency-Key": idempotencyKey },
  });
  return response.data as AnnotationTask;
}

export async function updateGenericAnnotationTaskConfiguration(taskId: string, payload: GenericTaskConfigurationPayload) {
  const response = await apiClient.put(`/annotation-tasks/${encodeURIComponent(taskId)}/configuration`, payload);
  return response.data as AnnotationTask;
}

export async function createAnnotationPreview(taskId: string, taskRevision: number, configHash: string) {
  const response = await apiClient.post(`/annotation-tasks/${taskId}/preview`, { task_revision: taskRevision, config_hash: configHash });
  return response.data as { operation_id: string; preview_id: string; task_revision: number; status: string; dispatch_id?: string | null };
}

export async function getAnnotationTask(taskId: string): Promise<AnnotationTask> {
  const response = await apiClient.get(`/annotation-tasks/${encodeURIComponent(taskId)}`);
  return response.data as AnnotationTask;
}

export async function deleteAnnotationTask(taskId: string): Promise<void> {
  await apiClient.delete(`/annotation-tasks/${encodeURIComponent(taskId)}`);
}

export async function listAnnotationPreviews(taskId: string, limit = 20, cursor?: string): Promise<{ items: AnnotationPreview[]; total: number; next_cursor: string | null }> {
  const response = await apiClient.get(`/annotation-tasks/${encodeURIComponent(taskId)}/previews`, { params: { limit, cursor } });
  return response.data as { items: AnnotationPreview[]; total: number; next_cursor: string | null };
}

export async function getAnnotationPreview(taskId: string, previewId: string): Promise<AnnotationPreview> {
  const response = await apiClient.get(`/annotation-tasks/${encodeURIComponent(taskId)}/previews/${encodeURIComponent(previewId)}`);
  return response.data as AnnotationPreview;
}

export async function transitionAnnotationTask(taskId: string, taskRevision: number, action: string, previewId?: string) {
  const response = await apiClient.post(`/annotation-tasks/${taskId}/transition`, { task_revision: taskRevision, action, preview_id: previewId });
  return response.data as AnnotationTask;
}

export async function listAnnotationPreviewSamples(taskId: string, previewId: string, limit = 50, cursor?: string) {
  const response = await apiClient.get(`/annotation-tasks/${taskId}/previews/${previewId}/samples`, { params: { limit, cursor } });
  return response.data as { items: Array<{ id: string; sample_id: string; row_index: number; values: Record<string, unknown> }>; total: number; next_cursor: string | null };
}

export async function listAnnotationOperations(projectId: string, limit = 50, cursor?: string): Promise<{ items: AnnotationOperation[]; total: number; next_cursor: string | null }> {
  const response = await apiClient.get("/annotation-operations", { params: { project_id: projectId, limit, cursor } });
  return response.data as { items: AnnotationOperation[]; total: number; next_cursor: string | null };
}

export async function listAnnotationExecutionResults(taskId: string, operationId: string, limit = 50, cursor?: string) {
  const response = await apiClient.get(`/annotation-tasks/${encodeURIComponent(taskId)}/executions/${encodeURIComponent(operationId)}/results`, { params: { limit, cursor } });
  return response.data as { items: Array<{ id: string; sample_id: string; row_index: number; task_revision: number; values: Record<string, unknown>; provenance: Record<string, unknown>; status: string }>; total: number; next_cursor: string | null };
}

export async function listAnnotationExecutionStats(taskId: string, operationId: string, kind: "sample" | "cluster" | "rule" | "final_label", limit = 50, cursor?: string) {
  const response = await apiClient.get(`/annotation-tasks/${encodeURIComponent(taskId)}/executions/${encodeURIComponent(operationId)}/stats`, { params: { kind, limit, cursor } });
  return response.data as { items: Array<Record<string, unknown>>; total: number; next_cursor: string | null };
}
