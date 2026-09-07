import apiClient from "./client";

export type AutoMLTaskType =
  | "classification"
  | "multioutput_classification"
  | "regression"
  | "multioutput_regression";

export type AutoMLSearchMethod = "grid" | "random" | "bayesian" | "evolutionary" | "multi_fidelity";
export type AutoMLSearchStrength = "light" | "balanced" | "thorough" | "maximum";
// Values are execution seconds; the UI presents the approved 30/60/120/240-minute presets.
export type AutoMLTimeBudget = 1800 | 3600 | 7200 | 14400;

interface AutoMLRunPayloadBase {
  project_id: string;
  experiment_id: string;
  dataset_artifact_id: string;
  input_columns: string[];
  algorithm_ids: string[];
  search_method: AutoMLSearchMethod;
  max_trials: number;
  time_budget: AutoMLTimeBudget;
  search_strength: AutoMLSearchStrength;
  class_weight: boolean;
  cross_validation_enabled: boolean;
  cross_validation_folds: 2 | 3 | 4 | 5 | null;
}

export type AutoMLRunPayload =
  | (AutoMLRunPayloadBase & {
      task: "classification" | "regression";
      target_column: string;
      target_columns?: never;
    })
  | (AutoMLRunPayloadBase & {
      task: "multioutput_classification" | "multioutput_regression";
      target_columns: [string, string, ...string[]];
      target_column?: never;
    });

export interface TrainingJobCreate {
  project_id: string;
  experiment_id: string;
  dataset_artifact_id: string;
  name: string;
  target_column: string;
  task: "auto" | "classification" | "regression";
  total_epochs: number;
  monitor?: string;
  mode?: "min" | "max";
  patience?: number;
  min_delta?: number;
  restore_best?: boolean;
  checkpoint_interval?: number;
}

export interface TrainingJob {
  id: string;
  project_id?: string;
  project_name?: string | null;
  user_id?: string;
  created_by_id?: string | null;
  created_by_name?: string | null;
  experiment_id?: string | null;
  mlflow_run_id?: string | null;
  name?: string;
  operator_id?: string;
  status?: string;
  task_id?: string | null;
  worker_id?: string | null;
  params?: Record<string, unknown>;
  dataset_artifact_id?: string | null;
  model_artifact_id?: string | null;
  model_library_id?: string | null;
  current_epoch?: number;
  total_epochs?: number | null;
  latest_checkpoint_uri?: string | null;
  best_checkpoint_uri?: string | null;
  resumed_from_job_id?: string | null;
  resumed_from_run_id?: string | null;
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

export interface TrainingCheckpoint {
  path: string;
  uri: string;
  is_dir: boolean;
  file_size: number | null;
}

export interface TensorBoardSession {
  session_id: string;
  run_id: string;
  expires_at: number;
  token: string;
  url: string;
}

export async function createTrainingJob(payload: TrainingJobCreate) {
  const response = await apiClient.post("/training/run", payload);
  return response.data as { job_id: string; status: "queued"; task_id: string };
}

export async function listTrainingJobs(projectId?: string): Promise<TrainingJob[]> {
  const response = await apiClient.get("/training/jobs", {
    params: projectId ? { project_id: projectId } : undefined,
  });
  return normalizeItems<TrainingJob>(response.data);
}

export async function getTrainingJob(jobId: string): Promise<TrainingJob> {
  const response = await apiClient.get(`/training/jobs/${jobId}`);
  return response.data;
}

export async function listTrainingCheckpoints(jobId: string): Promise<TrainingCheckpoint[]> {
  const response = await apiClient.get(`/training/jobs/${jobId}/checkpoints`);
  return Array.isArray(response.data?.checkpoints) ? response.data.checkpoints : [];
}

export async function stopTrainingJob(jobId: string): Promise<{ job_id: string; status: string }> {
  const response = await apiClient.post(`/training/jobs/${jobId}/stop`);
  return response.data;
}

export async function deleteTrainingJob(jobId: string): Promise<{ deleted: number }> {
  const response = await apiClient.post("/training/batch-delete", { ids: [jobId] });
  return response.data as { deleted: number };
}

export async function resumeTrainingJob(
  jobId: string,
  checkpointPath?: string,
): Promise<{ job_id: string; status: string; task_id: string }> {
  const response = await apiClient.post(`/training/jobs/${jobId}/resume`, {
    ...(checkpointPath ? { checkpoint_path: checkpointPath } : {}),
  });
  return response.data;
}

export async function createTensorBoardSession(jobId: string): Promise<TensorBoardSession> {
  const response = await apiClient.post(`/training/jobs/${jobId}/tensorboard-session`);
  return response.data;
}

function normalizeItems<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  if (value && typeof value === "object" && Array.isArray((value as { items?: unknown }).items)) {
    return (value as { items: T[] }).items;
  }
  return [];
}
