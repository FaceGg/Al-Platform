import apiClient from "./client";

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export interface ExperimentCreate {
  project_id: string;
  name: string;
  description?: string;
}

export interface Experiment {
  id: string;
  project_id: string;
  created_by: string;
  name: string;
  description: string;
  mlflow_experiment_id: string;
  created_at: string;
  updated_at: string;
  run_count: number;
}

export interface MetricPoint {
  key: string;
  value: number;
  timestamp: number;
  step: number;
}

export interface ExperimentRun {
  run_id: string;
  experiment_id: string;
  run_name: string | null;
  status: string;
  start_time: number | null;
  end_time: number | null;
  artifact_uri: string | null;
  params: Record<string, string>;
  metrics: Record<string, number>;
  tags: Record<string, string>;
  parent_run_id: string | null;
}

export interface ComparedRun extends ExperimentRun {
  metric_history: Record<string, MetricPoint[]>;
  missing: { params: string[]; metrics: string[] };
}

export interface RunComparison {
  run_ids: string[];
  param_names: string[];
  metric_names: string[];
  runs: ComparedRun[];
}

export async function createExperiment(payload: ExperimentCreate): Promise<Experiment> {
  const response = await apiClient.post("/experiments", payload);
  return response.data;
}

export async function deleteExperiment(experimentId: string): Promise<void> {
  await apiClient.delete(`/experiments/${experimentId}`);
}

export async function listExperiments(projectId: string): Promise<Experiment[]> {
  const response = await apiClient.get("/experiments", { params: { project_id: projectId } });
  return normalizeItems<Experiment>(response.data);
}

export async function getExperiment(experimentId: string): Promise<Experiment> {
  const response = await apiClient.get(`/experiments/${experimentId}`);
  return response.data;
}

export async function listExperimentRuns(
  experimentId: string,
  limit = 50,
  offset = 0,
): Promise<{ items: ExperimentRun[]; total: number }> {
  const response = await apiClient.get(`/experiments/${experimentId}/runs`, {
    params: { limit, offset },
  });
  return {
    items: normalizeItems<ExperimentRun>(response.data),
    total: Number(response.data?.total ?? normalizeItems<ExperimentRun>(response.data).length),
  };
}

export async function compareExperimentRuns(
  experimentId: string,
  runIds: string[],
): Promise<RunComparison> {
  const response = await apiClient.post(`/experiments/${experimentId}/compare`, {
    run_ids: runIds,
  });
  return response.data;
}

function normalizeItems<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  if (value && typeof value === "object" && Array.isArray((value as { items?: unknown }).items)) {
    return (value as { items: T[] }).items;
  }
  return [];
}
