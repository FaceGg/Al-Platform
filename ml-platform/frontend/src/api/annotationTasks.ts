import apiClient from "./client";

export type AnnotationTask = {
  id: string;
  project_id: string;
  mode: "manual" | "automatic";
  status: string;
  task_revision: number;
  sample_scope: Record<string, unknown>;
};

export async function listAnnotationTasks(projectId: string, limit = 50, cursor?: string) {
  const response = await apiClient.get("/annotation-tasks", { params: { project_id: projectId, limit, cursor } });
  return response.data as { items: AnnotationTask[]; total: number; next_cursor: string | null };
}

export async function createAnnotationPreview(taskId: string, taskRevision: number, configHash: string) {
  const response = await apiClient.post(`/annotation-tasks/${taskId}/preview`, { task_revision: taskRevision, config_hash: configHash });
  return response.data as { operation_id: string; preview_id: string; task_revision: number; status: string };
}

export async function transitionAnnotationTask(taskId: string, taskRevision: number, action: string, previewId?: string) {
  const response = await apiClient.post(`/annotation-tasks/${taskId}/transition`, { task_revision: taskRevision, action, preview_id: previewId });
  return response.data as AnnotationTask;
}
