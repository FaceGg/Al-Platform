import apiClient from "./client";

export type JobStatus =
  | "queued"
  | "submitted"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "timed_out"
  | "orphaned";

export interface JobRun {
  id: string;
  project_id: string;
  cluster_id: string;
  namespace: string;
  job_name: string;
  image_ref: string;
  command_json: string[];
  args_json: string[];
  resource_json: Record<string, number>;
  status: JobStatus;
  status_detail: string | null;
  error_code: string | null;
  revision: number;
  timeout_seconds: number;
  exit_code: number | null;
  submitted_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
  operation_state?: string | null;
  operation_progress?: number | null;
  replayed?: boolean;
}

export interface JobRunLogPage {
  text: string;
  next_cursor: number;
  end_of_stream: boolean;
}

export async function listJobRuns(
  offset = 0,
  limit = 50,
  clusterId?: string,
): Promise<{ items: JobRun[]; total: number }> {
  const res = await apiClient.get("/kubernetes/jobs", {
    params: { offset, limit, ...(clusterId ? { cluster_id: clusterId } : {}) },
  });
  return res.data;
}

export async function getJobRun(jobId: string): Promise<JobRun> {
  const res = await apiClient.get(`/kubernetes/jobs/${jobId}`);
  return res.data;
}

export async function cancelJobRun(jobId: string, reason: string): Promise<JobRun> {
  const res = await apiClient.post(`/kubernetes/jobs/${jobId}/cancel`, null, {
    params: { reason },
  });
  return res.data;
}

export async function reconcileJobRun(jobId: string): Promise<JobRun> {
  const res = await apiClient.post(`/kubernetes/jobs/${jobId}/reconcile`);
  return res.data;
}

export async function getJobRunLogs(jobId: string, cursor = 0): Promise<JobRunLogPage> {
  const res = await apiClient.get(`/kubernetes/jobs/${jobId}/logs`, { params: { cursor } });
  return res.data;
}
