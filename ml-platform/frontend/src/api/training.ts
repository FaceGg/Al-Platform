import apiClient from "./client";

export interface TrainingJobCreate {
  project_id: string;
  dataset_artifact_id: string;
  name: string;
  operator_id: string;
  params: Record<string, unknown>;
}

export interface TrainingJob {
  id: string;
  project_id?: string;
  name?: string;
  operator_id?: string;
  status?: string;
  params?: Record<string, unknown>;
  dataset_artifact_id?: string | null;
  model_artifact_id?: string | null;
  model_library_id?: string | null;
  feature_schema?: Array<Record<string, unknown>>;
  target_schema?: Record<string, unknown>;
  preprocessing?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  logs?: Array<Record<string, unknown>>;
  error_code?: string | null;
  error_details?: Record<string, unknown> | null;
  error_message?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export async function createTrainingJob(payload: TrainingJobCreate) {
  const response = await apiClient.post("/training/run", payload);
  return response.data;
}

export async function listTrainingJobs(projectId?: string): Promise<TrainingJob[]> {
  const response = await apiClient.get("/training/jobs", {
    params: projectId ? { project_id: projectId } : undefined,
  });
  return response.data.items || response.data || [];
}

export async function getTrainingJob(jobId: string): Promise<TrainingJob> {
  const response = await apiClient.get(`/training/jobs/${jobId}`);
  return response.data;
}
