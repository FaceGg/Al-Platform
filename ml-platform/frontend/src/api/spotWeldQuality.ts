import apiClient from "./client";

export type QualityRunStatus = "queued" | "validating" | "running" | "completed" | "failed";
export type QualityLabelMode = "automatic" | "manual";
export type QualityAlgorithmId =
  | "lightgbm"
  | "xgboost"
  | "catboost"
  | "gbdt"
  | "random_forest"
  | "extra_trees"
  | "hist_gradient_boosting";
export type QualitySearchMethod = "grid" | "random" | "bayesian" | "evolutionary" | "multi_fidelity";

export interface QualitySearchConfig {
  contract?: "optuna_v1" | string;
  method: QualitySearchMethod;
  max_trials: number;
  time_budget: number;
}

export interface QualityFamilyResult {
  algorithm_id: QualityAlgorithmId;
  name: string;
  status: string;
  best_score?: number | null;
  auc?: number | null;
  f1?: number | null;
  auc_std?: number | null;
  f1_std?: number | null;
  best_params?: Record<string, unknown>;
  completed_trials?: number;
  pruned_trials?: number;
  failed_trials?: number;
  training_time_seconds?: number | null;
  error_code?: string | null;
  error_message?: string | null;
}

export interface QualityAnnotationProgress {
  annotated_count: number;
  total_count: number;
  percent: number;
}

export interface QualityEvaluationConfig {
  cross_validation_enabled: boolean;
  cross_validation_folds: 3 | 4 | 5 | null;
}

export interface QualityRuleConfig {
  strong_splatter_min: number;
  weak_splatter_value: number;
  spotdiameter_small_min: number;
  spotdiameter_small_max: number;
  spotdiameter_large_min: number;
  energy_dev_sigma: number;
  current_max_diff_percentile: number;
  power_std_percentile: number;
  spatter_cluster_id: number;
  spatter_cluster_min_strength: number;
}

export interface QualityRun {
  id: string;
  status: QualityRunStatus | string;
  dataset_artifact_id?: string;
  sample_count?: number;
  valid_rows?: number;
  feature_version?: string;
  rule_set_version?: string;
  statistics?: Record<string, unknown>;
  automl_results?: QualityFamilyResult[];
  clustering_results?: Record<string, unknown>;
  output_artifacts?: Record<string, string>;
  error_code?: string | null;
  error_details?: { code?: string; message?: string; [key: string]: unknown } | null;
  selected_algorithm_ids?: QualityAlgorithmId[];
  search?: QualitySearchConfig;
  target_column?: string | null;
  target_column_created?: boolean;
  target_column_dtype?: string | null;
  target_schema?: {
    name?: string;
    dtype?: string;
    classes?: string[];
    class_count?: number;
    created?: boolean;
  } | null;
  input_columns?: string[];
  evaluation?: QualityEvaluationConfig;
  label_mode?: QualityLabelMode;
  rule_config?: Partial<QualityRuleConfig>;
  annotation_progress?: QualityAnnotationProgress;
  modeling_progress?: {
    completed?: number;
    total?: number;
    percent?: number;
  };
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

export interface QualityDatasetColumn {
  name: string;
  dtype: string;
}

export interface QualityDatasetColumns {
  columns: QualityDatasetColumn[];
  row_count: number;
  target_candidates: string[];
}

export interface QualityClusterPreview {
  model_id: string;
  best_k: number;
  silhouette_scores: Record<string, number>;
  cluster_counts: Record<string, number>;
  cluster_ids: number[];
  pca_coordinates: number[][];
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

export async function deleteQualityRun(projectId: string, runId: string): Promise<{ deleted: number; run_id: string }> {
  const response = await apiClient.delete(`/projects/${projectId}/spot-weld/runs/${runId}`);
  return response.data as { deleted: number; run_id: string };
}

export async function updateQualityRunRules(
  projectId: string,
  runId: string,
  ruleConfig: QualityRuleConfig,
): Promise<QualityRun> {
  const response = await apiClient.put(
    `/projects/${projectId}/spot-weld/runs/${runId}/rules`,
    { rule_config: ruleConfig },
  );
  return response.data as QualityRun;
}

export async function submitQualityRunForReview(projectId: string, runId: string): Promise<{ run_id: string; submitted_count: number; labeled_count: number }> {
  const response = await apiClient.post(`/projects/${projectId}/spot-weld/runs/${runId}/submit-review`);
  return response.data as { run_id: string; submitted_count: number; labeled_count: number };
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

export async function deleteQualityLabel(
  projectId: string,
  runId: string,
  sampleId: string,
): Promise<QualitySample> {
  const response = await apiClient.delete(
    `/projects/${projectId}/spot-weld/runs/${runId}/samples/${sampleId}/labels`,
  );
  return response.data as QualitySample;
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

export async function listQualityDatasetColumns(
  projectId: string,
  artifactId: string,
): Promise<QualityDatasetColumns> {
  const response = await apiClient.get(
    `/projects/${projectId}/spot-weld/datasets/${artifactId}/columns`,
  );
  const data = (response.data || {}) as Partial<QualityDatasetColumns>;
  return {
    columns: Array.isArray(data.columns) ? data.columns : [],
    row_count: Number(data.row_count || 0),
    target_candidates: Array.isArray(data.target_candidates) ? data.target_candidates : [],
  };
}

export async function previewQualityClusters(
  projectId: string,
  payload: { dataset_artifact_id: string; selected_model_id: string },
): Promise<QualityClusterPreview> {
  const response = await apiClient.post(`/projects/${projectId}/spot-weld/cluster-preview`, payload);
  return response.data as QualityClusterPreview;
}

export async function downloadQualityArtifact(
  projectId: string,
  runId: string,
  artifactKey: "report" | "schema" | "model" | "model_comparison_chart" | "cluster_pca_chart" | "feature_importance_chart" | "warning_distribution_chart" | "waveform_comparison_chart",
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

export interface SavedLabeledDataset {
  id: string;
  artifact_id: string;
  name: string;
  format?: string;
  row_count?: number;
  source_dataset_artifact_id?: string;
  quality_run_id?: string;
}

export async function saveLabeledDataset(
  projectId: string,
  runId: string,
  labelSource: "current" | "automatic" = "current",
): Promise<SavedLabeledDataset> {
  const response = await apiClient.post(
    `/projects/${projectId}/spot-weld/runs/${runId}/save-labeled-dataset`,
    { label_source: labelSource },
  );
  return response.data as SavedLabeledDataset;
}

export async function createQualityRun(
  projectId: string,
  payload: {
    dataset_artifact_id: string;
    field_mapping?: Record<string, string>;
    algorithm_ids?: QualityAlgorithmId[];
    search_method?: QualitySearchMethod;
    max_trials?: number;
    time_budget?: number;
    target_column?: string;
    target_column_created?: boolean;
    target_column_dtype?: "int" | "float" | "string";
    selected_model_id?: string;
    weak_supervision?: boolean;
    cluster_labels?: Record<string, string>;
    process_rules?: Array<Record<string, string | number | boolean>>;
    input_columns?: string[];
    cross_validation_enabled?: boolean;
    cross_validation_folds?: 3 | 4 | 5 | null;
    label_mode?: QualityLabelMode;
    rule_config?: Partial<QualityRuleConfig>;
  },
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
  options: {
    label_mode?: QualityLabelMode;
    rule_config?: Partial<QualityRuleConfig>;
    algorithm_ids?: QualityAlgorithmId[];
    search_method?: QualitySearchMethod;
    max_trials?: number;
    time_budget?: number;
    target_column?: string;
    target_column_created?: boolean;
    target_column_dtype?: "int" | "float" | "string";
    selected_model_id?: string;
    weak_supervision?: boolean;
    cluster_labels?: Record<string, string>;
    process_rules?: Array<Record<string, string | number | boolean>>;
    input_columns?: string[];
    cross_validation_enabled?: boolean;
    cross_validation_folds?: 3 | 4 | 5 | null;
  } = {},
): Promise<QualityDatasetValidation> {
  const response = await apiClient.post(`/projects/${projectId}/spot-weld/validate`, {
    dataset_artifact_id: datasetArtifactId,
    field_mapping: fieldMapping,
    ...options,
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
