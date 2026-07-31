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
  output_artifacts?: Record<string, string>;
  error_code?: string | null;
  selected_candidate_ids?: string[];
}

export interface QualityLabelSnapshot {
  id: string;
  name: string;
  sample_count: number;
  label_counts?: Record<string, number>;
  created_at?: string | null;
  label_source?: "approved" | "automatic";
}

export interface QualityModel {
  id: string;
  name: string;
  version?: string;
  status?: string;
  framework?: string;
  backbone?: string;
  metrics?: Record<string, number | null>;
  params: Record<string, string>;
  model_artifact_id?: string | null;
  format?: string;
  tags?: string[];
}

export interface QualityTrainingResult {
  snapshot_id: string;
  run_id: string;
  model: QualityModel;
  output_artifacts: Record<string, string>;
}

export interface QualityWarning {
  id: string;
  run_id: string;
  display_id: string;
  warning_level: string;
  defect_probability?: number | null;
  current_label?: string | null;
  automatic_label?: string | null;
}

export interface QualityWarningSummary {
  counts: Record<"critical" | "warning" | "notice" | "none", number>;
  items: QualityWarning[];
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
  rule_hits?: Array<{ code: string; label: string; reason?: string }>;
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

export interface QualityDatasetValidation {
  row_count: number;
  valid_rows: number;
  invalid_rows: number;
  errors: Array<{ code: string; message?: string; row_index?: number; field_name?: string }>;
}

export interface QualityDatasetArtifact {
  id?: string;
  artifact_id: string;
  name?: string;
  row_count?: number;
  sha256?: string;
}

function items<T>(data: { items?: T[] } | T[]): T[] {
  return Array.isArray(data) ? data : data.items || [];
}

export async function listQualityRuns(projectId: string): Promise<QualityRun[]> {
  const response = await apiClient.get(`/projects/${projectId}/spot-weld/runs`);
  return items(response.data);
}

export async function getQualityRun(projectId: string, runId: string): Promise<QualityRun> {
  const response = await apiClient.get(`/projects/${projectId}/spot-weld/runs/${runId}`);
  return response.data as QualityRun;
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

export async function createQualityLabelSnapshot(
  projectId: string,
  runId: string,
  name: string,
  labelSource: "approved" | "automatic" = "approved",
): Promise<QualityLabelSnapshot> {
  const response = await apiClient.post(
    `/projects/${projectId}/spot-weld/runs/${runId}/label-snapshots`,
    { name, label_source: labelSource },
  );
  return response.data as QualityLabelSnapshot;
}

export async function listQualityLabelSnapshots(
  projectId: string,
  runId: string,
): Promise<QualityLabelSnapshot[]> {
  const response = await apiClient.get(
    `/projects/${projectId}/spot-weld/runs/${runId}/label-snapshots`,
  );
  return items<QualityLabelSnapshot>(response.data);
}

export async function trainQualityLabelSnapshot(
  projectId: string,
  runId: string,
  snapshotId: string,
): Promise<QualityTrainingResult> {
  const response = await apiClient.post(
    `/projects/${projectId}/spot-weld/runs/${runId}/label-snapshots/${snapshotId}/train`,
  );
  return response.data as QualityTrainingResult;
}

export async function getQualityModel(
  projectId: string,
  runId: string,
): Promise<QualityModel | null> {
  const response = await apiClient.get(
    `/projects/${projectId}/spot-weld/runs/${runId}/quality-model`,
  );
  const value = response.data as unknown;
  return value && typeof value === "object" && !Array.isArray(value)
    && typeof (value as { id?: unknown }).id === "string"
    && typeof (value as { name?: unknown }).name === "string"
    ? value as QualityModel
    : null;
}

export async function listQualityModels(projectId: string): Promise<QualityModel[]> {
  const response = await apiClient.get(`/projects/${projectId}/spot-weld/models`);
  return items<QualityModel>(response.data);
}

export async function downloadQualityArtifact(
  projectId: string,
  runId: string,
  artifactKey: "report" | "schema" | "model",
): Promise<Blob> {
  const response = await apiClient.get(
    `/projects/${projectId}/spot-weld/runs/${runId}/artifacts/${artifactKey}/download`,
    { responseType: "blob" },
  );
  return response.data as Blob;
}

export type QualityAnnotationExportFormat = "csv" | "xlsx";

export async function downloadQualityAnnotationExport(
  projectId: string,
  runId: string,
  format: QualityAnnotationExportFormat,
): Promise<Blob> {
  const response = await apiClient.get(
    `/projects/${projectId}/spot-weld/runs/${runId}/annotations/export`,
    { params: { format }, responseType: "blob" },
  );
  return response.data as Blob;
}

export async function createQualityRun(
  projectId: string,
  payload: { dataset_artifact_id: string; field_mapping?: Record<string, string>; candidate_ids?: string[] },
) {
  const response = await apiClient.post(`/projects/${projectId}/spot-weld/runs`, payload);
  return response.data as QualityRun;
}

export async function uploadQualityDataset(projectId: string, file: File): Promise<QualityDatasetArtifact> {
  const body = new FormData();
  body.append("file", file);
  const response = await apiClient.post(`/projects/${projectId}/datasets/upload`, body);
  return response.data;
}

export async function validateQualityDataset(
  projectId: string,
  datasetArtifactId: string,
  fieldMapping: Record<string, string> = {},
): Promise<QualityDatasetValidation> {
  const response = await apiClient.post(`/projects/${projectId}/spot-weld/validate`, {
    dataset_artifact_id: datasetArtifactId,
    field_mapping: fieldMapping,
  });
  return response.data;
}

export async function createQualityDemoDataset(
  projectId: string,
  rowCount: number = 60,
): Promise<QualityDatasetArtifact> {
  const response = await apiClient.post(`/projects/${projectId}/spot-weld/demo-dataset`, {
    row_count: rowCount,
  });
  return response.data;
}

export async function getQualityWarningSummary(projectId: string): Promise<QualityWarningSummary> {
  const response = await apiClient.get(`/projects/${projectId}/spot-weld/warnings`);
  return response.data as QualityWarningSummary;
}
