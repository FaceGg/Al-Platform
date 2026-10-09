import apiClient from "./client";

export type NotebookStatus =
  | "starting"
  | "running"
  | "stopping"
  | "stopped"
  | "failed"
  | "terminated";

export interface NotebookSession {
  id: string;
  project_id: string;
  user_id: string;
  cluster_id: string;
  namespace: string;
  job_name: string;
  image_ref: string;
  resource_json: Record<string, unknown>;
  status: NotebookStatus;
  idle_timeout_seconds: number;
  error_code: string | null;
  last_activity_at: string | null;
  started_at: string | null;
  terminated_at: string | null;
  created_at: string | null;
  replayed?: boolean;
}

export interface ContainerImage {
  id: string;
  project_id: string | null;
  registry: string;
  repository: string;
  digest: string;
  visibility: "project" | "platform";
  scan_status: "unknown" | "pending" | "passed" | "failed";
  scan_report_ref: string | null;
  source: "manual_registry" | "build";
  description: string | null;
  created_at: string | null;
}

export async function listNotebooks(offset = 0, limit = 50): Promise<{ items: NotebookSession[]; total: number }> {
  const res = await apiClient.get("/notebooks", { params: { offset, limit } });
  return res.data;
}

export async function startNotebook(payload: {
  cluster_id: string;
  namespace?: string;
  image_ref: string;
  resources?: Record<string, number>;
  idle_timeout_seconds?: number;
}): Promise<NotebookSession> {
  const res = await apiClient.post("/notebooks", payload, {
    headers: { "Idempotency-Key": `nb-${Date.now()}-${Math.random().toString(36).slice(2)}` },
  });
  return res.data;
}

export async function stopNotebook(sessionId: string): Promise<NotebookSession> {
  const res = await apiClient.post(`/notebooks/${sessionId}/stop`, null, { params: { reason: "user stop" } });
  return res.data;
}

export async function reconcileNotebook(sessionId: string): Promise<NotebookSession> {
  const res = await apiClient.post(`/notebooks/${sessionId}/reconcile`);
  return res.data;
}

export async function openNotebook(sessionId: string): Promise<{ token: string; url: string; expires_in_seconds: number }> {
  const res = await apiClient.post(`/notebooks/${sessionId}/access`);
  return res.data;
}

export async function listImages(offset = 0, limit = 100): Promise<{ items: ContainerImage[]; total: number }> {
  const res = await apiClient.get("/images", { params: { offset, limit } });
  return res.data;
}

export async function registerImage(payload: {
  registry: string;
  repository: string;
  digest: string;
  visibility: "project" | "platform";
  scan_status: "unknown" | "pending" | "passed" | "failed";
  description?: string;
}): Promise<ContainerImage> {
  const res = await apiClient.post("/images", payload);
  return res.data;
}

export async function updateImage(
  imageId: string,
  payload: { scan_status?: "unknown" | "pending" | "passed" | "failed"; description?: string },
): Promise<ContainerImage> {
  const res = await apiClient.patch(`/images/${imageId}`, payload);
  return res.data;
}
