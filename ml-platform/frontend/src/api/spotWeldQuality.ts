import apiClient from "./client";

export type QualityRunStatus = "queued" | "validating" | "running" | "completed" | "failed";

export interface QualityRun {
  id: string;
  status: QualityRunStatus | string;
  dataset_artifact_id?: string;
  sample_count?: number;
  valid_rows?: number;
  feature_version?: string;
  rule_set_version?: string;
  statistics?: Record<string, unknown>;
  automl_results?: Array<Record<string, unknown>>;
  clustering_results?: Record<string, unknown>;
  error_code?: string | null;
}

export interface QualitySample {
  id: string;
  display_id: string;
  source_row_index?: number;
  automatic_label?: string | null;
  current_label?: string | null;
  review_status: string;
  warning_level?: string;
  defect_probability?: number | null;
  cluster_id?: number | null;
  rule_hits?: Array<Record<string, unknown>>;
  table_values?: Record<string, unknown>;
}

export interface QualityWaveforms {
  current: number[];
  voltage: number[];
  resistance: number[];
  power: number[];
}

export interface QualitySampleDetail extends QualitySample {
  waveforms: QualityWaveforms;
  feature_values?: Record<string, number>;
  current_note?: string | null;
}

export interface QualitySampleFilters {
  review_status?: string;
  warning_level?: string;
  label?: string;
  q?: string;
}

function items<T>(data: { items?: T[] } | T[]): T[] {
  return Array.isArray(data) ? data : data.items || [];
}

export async function listQualityRuns(projectId: string): Promise<QualityRun[]> {
  const response = await apiClient.get(`/projects/${projectId}/spot-weld/runs`);
  return items(response.data);
}

export async function listQualitySamples(
  projectId: string,
  runId: string,
  params: QualitySampleFilters = {},
): Promise<QualitySample[]> {
  const response = await apiClient.get(
    `/projects/${projectId}/spot-weld/runs/${runId}/samples`,
    { params },
  );
  return items(response.data);
}

export async function getQualitySample(
  projectId: string,
  runId: string,
  sampleId: string,
): Promise<QualitySampleDetail> {
  const response = await apiClient.get(
    `/projects/${projectId}/spot-weld/runs/${runId}/samples/${sampleId}`,
  );
  return response.data;
}

export async function submitQualityLabel(
  projectId: string,
  runId: string,
  sampleId: string,
  payload: { label: string; note?: string },
) {
  const response = await apiClient.post(
    `/projects/${projectId}/spot-weld/runs/${runId}/samples/${sampleId}/labels`,
    payload,
  );
  return response.data;
}

export async function reviewQualityLabel(
  projectId: string,
  runId: string,
  sampleId: string,
  payload: { decision: "approved" | "returned"; comment?: string },
) {
  const response = await apiClient.post(
    `/projects/${projectId}/spot-weld/runs/${runId}/samples/${sampleId}/review`,
    payload,
  );
  return response.data;
}

export async function createQualityRun(
  projectId: string,
  payload: { dataset_artifact_id: string; field_mapping?: Record<string, string> },
) {
  const response = await apiClient.post(`/projects/${projectId}/spot-weld/runs`, payload);
  return response.data as QualityRun;
}

export async function getQualityWarningSummary(projectId: string) {
  const response = await apiClient.get(`/projects/${projectId}/spot-weld/warnings`);
  return response.data;
}
