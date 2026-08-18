import apiClient from "./client";

export type ProjectRole = "owner" | "editor" | "operator" | "viewer";
export type ModelSourceKind = "platform_joblib" | "onnx_artifact";
export type ApprovalStatus = "pending" | "approved" | "rejected" | "archived";
export type DesiredState = "stopped" | "running";
export type ObservedState = "stopped" | "starting" | "running" | "stopping" | "failed";

export interface ProjectOption {
  id: string;
  name: string;
  project_role: ProjectRole;
}

export interface FeatureField {
  name: string;
  dtype: string;
}

export interface OutputSchema {
  name: string;
  dtype: string;
  task: "classification" | "regression";
}

export interface RegisteredModel {
  id: string;
  project_id: string;
  name: string;
  description: string;
  latest_version: number | null;
  latest_approval_status: ApprovalStatus | null;
  created_at: string | null;
}

export interface ModelVersion {
  id: string;
  registered_model_id: string;
  version_number: number;
  source_kind: ModelSourceKind;
  framework: string;
  algorithm: string;
  feature_schema: FeatureField[];
  output_schema: OutputSchema;
  metrics: Record<string, number | string | boolean | null>;
  conversion_metadata: Record<string, unknown>;
  approval_status: ApprovalStatus;
  approval_comment: string;
  created_at: string | null;
}

export interface InferenceDeployment {
  id: string;
  project_id: string;
  name: string;
  model_version_id: string;
  desired_state: DesiredState;
  observed_state: ObservedState;
  last_error_code: string | null;
  last_checked_at: string | null;
  created_at: string | null;
}

export type RecordValue = string | number | boolean;
export type InferenceRecord = Record<string, RecordValue>;

export interface PredictionResult {
  deployment_id: string;
  model_version_id: string;
  version_number: number;
  predictions: unknown[];
  probabilities?: unknown[];
  duration_ms: number;
}

export type RolloutStrategy = "immediate" | "canary" | "rolling";
export type RolloutState = "pending" | "preloading" | "progressing" | "paused" | "completed" | "failed" | "rolled_back";
export type RevisionStatus = "draft" | "candidate" | "stable" | "superseded" | "failed";

export interface DeploymentTarget {
  model_version_id: string;
  weight_bps: number;
}

export interface DeploymentRevision {
  id: string;
  deployment_id: string;
  revision_number: number;
  strategy: RolloutStrategy;
  status: RevisionStatus;
  targets: DeploymentTarget[];
  created_at: string | null;
  activated_at: string | null;
}

export interface DeploymentRollout {
  id: string;
  deployment_id: string;
  from_revision_id: string | null;
  to_revision_id: string;
  state: RolloutState;
  current_step: number;
  lock_version: number;
  step_schedule: number[];
  thresholds: Record<string, number>;
  last_error_code: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  targets: DeploymentTarget[];
}

export interface InferenceApiKey {
  id: string;
  prefix: string;
  scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string | null;
}

export interface CreatedInferenceApiKey extends InferenceApiKey {
  plaintext: string;
}

export interface InferenceMetricBucket {
  bucket_start: string;
  request_count: number;
  success_count: number;
  error_count: number;
  limited_count: number;
  load_failure_count: number;
  latency_buckets: Record<string, number>;
  traffic_weights: Record<string, number>;
}

export interface InferenceMetricSummary {
  request_count: number;
  success_count?: number;
  error_count: number;
  limited_count?: number;
  load_failure_count?: number;
  average_batch_size?: number;
  average_latency_ms?: number;
  max_latency_ms?: number;
  p50_latency_ms?: number | null;
  p95_latency_ms?: number | null;
  p99_latency_ms?: number | null;
  latency_buckets?: Record<string, number>;
  traffic_weights?: Record<string, number>;
}

export interface InferenceMetricPage {
  items: InferenceMetricBucket[];
  summary: InferenceMetricSummary;
  page: number;
  page_size: number;
}

export interface InferenceRequestLog {
  id: string;
  request_id: string;
  deployment_id: string;
  revision_id: string | null;
  model_version_id: string | null;
  api_key_id: string | null;
  batch_size: number;
  duration_ms: number;
  status: "success" | "error" | "limited";
  error_code: string | null;
  occurred_at: string;
  expires_at: string;
}

export interface InferenceRequestLogPage {
  items: InferenceRequestLog[];
  page: number;
  page_size: number;
}

export interface ModelCard {
  id: string;
  model_version_id: string;
  operational_guidance: string;
  guidance_revision: number;
  approval_status: ApprovalStatus;
  release_status: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface InferenceQuery {
  since: string;
  until: string;
  page?: number;
  page_size?: number;
}

export interface ListResponse<T> {
  items: T[];
  total: number;
}

function normalizeList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === "object" && Array.isArray((data as { items?: unknown }).items)) {
    return (data as { items: T[] }).items;
  }
  return [];
}

function normalizePagedList<T>(data: unknown): ListResponse<T> {
  if (Array.isArray(data)) return { items: data as T[], total: data.length };
  if (data && typeof data === "object") {
    const value = data as { items?: unknown; total?: unknown };
    if (Array.isArray(value.items) && typeof value.total === "number") {
      return { items: value.items as T[], total: value.total };
    }
  }
  return { items: [], total: 0 };
}

function commandPayload(lockVersion?: number): { expected_lock_version?: number } {
  return lockVersion === undefined ? {} : { expected_lock_version: lockVersion };
}

const METRIC_PAGE_SIZE = 200;
const LATENCY_BOUNDARIES = [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000] as const;

function metricPercentile(histogram: Record<string, number>, percentile: number): number | null {
  const total = Object.values(histogram).reduce((sum, count) => sum + Math.max(0, count), 0);
  if (total === 0) return null;
  const threshold = Math.ceil(total * percentile);
  let seen = 0;
  for (const boundary of LATENCY_BOUNDARIES) {
    seen += Math.max(0, histogram[String(boundary)] || 0);
    if (seen >= threshold) return boundary;
  }
  return LATENCY_BOUNDARIES[LATENCY_BOUNDARIES.length - 1];
}

function summarizeMetricBuckets(items: InferenceMetricBucket[]): InferenceMetricSummary {
  const latencyBuckets: Record<string, number> = {};
  let trafficWeights: Record<string, number> = {};
  let requestCount = 0;
  let successCount = 0;
  let errorCount = 0;
  let limitedCount = 0;
  let loadFailureCount = 0;

  for (const bucket of items) {
    requestCount += bucket.request_count || 0;
    successCount += bucket.success_count || 0;
    errorCount += bucket.error_count || 0;
    limitedCount += bucket.limited_count || 0;
    loadFailureCount += bucket.load_failure_count || 0;
    for (const [boundary, count] of Object.entries(bucket.latency_buckets || {})) {
      latencyBuckets[boundary] = (latencyBuckets[boundary] || 0) + Math.max(0, count || 0);
    }
    if (Object.keys(bucket.traffic_weights || {}).length > 0) trafficWeights = bucket.traffic_weights;
  }

  return {
    request_count: requestCount,
    success_count: successCount,
    error_count: errorCount,
    limited_count: limitedCount,
    load_failure_count: loadFailureCount,
    latency_buckets: latencyBuckets,
    p50_latency_ms: metricPercentile(latencyBuckets, 0.5),
    p95_latency_ms: metricPercentile(latencyBuckets, 0.95),
    p99_latency_ms: metricPercentile(latencyBuckets, 0.99),
    traffic_weights: trafficWeights,
  };
}

export async function listRegisteredModels(projectId: string): Promise<RegisteredModel[]> {
  const response = await apiClient.get(`/projects/${projectId}/registered-models`);
  return normalizeList<RegisteredModel>(response.data);
}

export async function createRegisteredModel(
  projectId: string,
  payload: { name: string; description: string },
): Promise<RegisteredModel> {
  const response = await apiClient.post(`/projects/${projectId}/registered-models`, payload);
  return response.data;
}

export async function listModelVersions(modelId: string): Promise<ModelVersion[]> {
  const response = await apiClient.get(`/registered-models/${modelId}/versions`);
  return normalizeList<ModelVersion>(response.data);
}

export async function registerPlatformVersion(
  modelId: string,
  sourceModelLibraryId: string,
): Promise<ModelVersion> {
  const response = await apiClient.post(`/registered-models/${modelId}/versions`, {
    source_kind: "platform_joblib",
    source_model_library_id: sourceModelLibraryId,
  });
  return response.data;
}

export async function uploadOnnxArtifact(projectId: string, file: File) {
  const body = new FormData();
  body.append("file", file);
  const response = await apiClient.post(`/projects/${projectId}/model-artifacts`, body);
  return response.data as { id: string; name: string; format: string; file_size: number; sha256: string };
}

export async function registerOnnxVersion(
  modelId: string,
  payload: {
    source_artifact_id: string;
    feature_schema: FeatureField[];
    output_schema: OutputSchema;
  },
): Promise<ModelVersion> {
  const response = await apiClient.post(`/registered-models/${modelId}/versions`, {
    source_kind: "onnx_artifact",
    ...payload,
  });
  return response.data;
}

export async function approveModelVersion(versionId: string, comment = ""): Promise<ModelVersion> {
  const response = await apiClient.post(`/model-versions/${versionId}/approve`, { comment });
  return response.data;
}

export async function rejectModelVersion(versionId: string, comment: string): Promise<ModelVersion> {
  const response = await apiClient.post(`/model-versions/${versionId}/reject`, { comment });
  return response.data;
}

export async function listDeployments(projectId: string): Promise<InferenceDeployment[]> {
  const response = await apiClient.get(`/projects/${projectId}/inference-deployments`);
  return normalizeList<InferenceDeployment>(response.data);
}

export async function createDeployment(
  projectId: string,
  payload: { name: string; model_version_id: string },
): Promise<InferenceDeployment> {
  const response = await apiClient.post(`/projects/${projectId}/inference-deployments`, payload);
  return response.data;
}

export async function deleteRegisteredModel(modelId: string): Promise<{ id: string }> {
  const response = await apiClient.delete(`/registered-models/${modelId}`);
  return response.data;
}

export async function deleteDeployment(deploymentId: string): Promise<{ id: string }> {
  const response = await apiClient.delete(`/inference-deployments/${deploymentId}`);
  return response.data;
}

export async function startDeployment(deploymentId: string): Promise<InferenceDeployment> {
  const response = await apiClient.post(`/inference-deployments/${deploymentId}/start`);
  return response.data;
}

export async function stopDeployment(deploymentId: string): Promise<InferenceDeployment> {
  const response = await apiClient.post(`/inference-deployments/${deploymentId}/stop`);
  return response.data;
}

export async function predictDeployment(
  deploymentId: string,
  records: InferenceRecord[],
): Promise<PredictionResult> {
  const response = await apiClient.post(`/inference-deployments/${deploymentId}/predict`, { records });
  return response.data;
}

export async function createRollout(
  deploymentId: string,
  payload: { strategy: RolloutStrategy; targets: DeploymentTarget[]; step_schedule?: number[]; max_error_rate?: number; max_p95_ms?: number },
): Promise<DeploymentRollout> {
  const response = await apiClient.post(`/inference-deployments/${deploymentId}/rollouts`, payload);
  return response.data;
}

export async function listRollouts(deploymentId: string): Promise<ListResponse<DeploymentRollout>> {
  const response = await apiClient.get(`/inference-deployments/${deploymentId}/rollouts`);
  return normalizePagedList<DeploymentRollout>(response.data);
}

async function commandRollout(
  deploymentId: string,
  rolloutId: string,
  action: "pause" | "resume" | "rollback",
  lockVersion?: number,
): Promise<DeploymentRollout> {
  const payload = commandPayload(lockVersion);
  const response = await apiClient.post(
    `/inference-deployments/${deploymentId}/rollouts/${rolloutId}/${action}`,
    payload,
  );
  return response.data;
}

export const pauseRollout = (deploymentId: string, rolloutId: string, lockVersion?: number) =>
  commandRollout(deploymentId, rolloutId, "pause", lockVersion);

export const resumeRollout = (deploymentId: string, rolloutId: string, lockVersion?: number) =>
  commandRollout(deploymentId, rolloutId, "resume", lockVersion);

export const rollbackRollout = (deploymentId: string, rolloutId: string, lockVersion?: number) =>
  commandRollout(deploymentId, rolloutId, "rollback", lockVersion);

export async function createInferenceApiKey(
  deploymentId: string,
  payload: { scopes: ["inference.predict"]; expires_at?: string | null },
): Promise<CreatedInferenceApiKey> {
  const response = await apiClient.post(`/inference-deployments/${deploymentId}/api-keys`, payload);
  return response.data;
}

export async function listInferenceApiKeys(deploymentId: string): Promise<ListResponse<InferenceApiKey>> {
  const response = await apiClient.get(`/inference-deployments/${deploymentId}/api-keys`);
  return normalizePagedList<InferenceApiKey>(response.data);
}

export async function rotateInferenceApiKey(keyId: string): Promise<CreatedInferenceApiKey> {
  const response = await apiClient.post(`/inference-api-keys/${keyId}/rotate`);
  return response.data;
}

export async function revokeInferenceApiKey(keyId: string): Promise<InferenceApiKey> {
  const response = await apiClient.post(`/inference-api-keys/${keyId}/revoke`);
  return response.data;
}

export async function listInferenceMetrics(deploymentId: string, query: InferenceQuery): Promise<InferenceMetricPage> {
  const response = await apiClient.get(`/inference-deployments/${deploymentId}/metrics`, { params: query });
  const data = response.data as Partial<InferenceMetricPage> | null;
  return {
    items: Array.isArray(data?.items) ? data.items as InferenceMetricBucket[] : [],
    summary: (data?.summary || { request_count: 0, error_count: 0 }) as InferenceMetricSummary,
    page: typeof data?.page === "number" ? data.page : query.page || 1,
    page_size: typeof data?.page_size === "number" ? data.page_size : query.page_size || 100,
  };
}

export async function listInferenceMetricWindow(
  deploymentId: string,
  query: Pick<InferenceQuery, "since" | "until">,
): Promise<InferenceMetricPage> {
  const items: InferenceMetricBucket[] = [];
  let page = 1;

  while (true) {
    const result = await listInferenceMetrics(deploymentId, {
      ...query,
      page,
      page_size: METRIC_PAGE_SIZE,
    });
    items.push(...result.items);
    if (result.items.length < METRIC_PAGE_SIZE) break;
    page += 1;
  }

  return {
    items,
    summary: summarizeMetricBuckets(items),
    page: 1,
    page_size: METRIC_PAGE_SIZE,
  };
}

export async function listInferenceRequestLogs(deploymentId: string, query: InferenceQuery): Promise<InferenceRequestLogPage> {
  const response = await apiClient.get(`/inference-deployments/${deploymentId}/request-logs`, { params: query });
  const data = response.data as Partial<InferenceRequestLogPage> | null;
  return {
    items: Array.isArray(data?.items) ? data.items as InferenceRequestLog[] : [],
    page: typeof data?.page === "number" ? data.page : query.page || 1,
    page_size: typeof data?.page_size === "number" ? data.page_size : query.page_size || 100,
  };
}

export async function getModelCard(versionId: string): Promise<ModelCard> {
  const response = await apiClient.get(`/model-versions/${versionId}/model-card`);
  return response.data;
}

export async function updateModelCardGuidance(cardId: string, operationalGuidance: string): Promise<ModelCard> {
  const response = await apiClient.patch(`/model-cards/${cardId}/guidance`, { operational_guidance: operationalGuidance });
  return response.data;
}

export async function exportModelCard(cardId: string): Promise<Record<string, unknown>> {
  const response = await apiClient.get(`/model-cards/${cardId}/export`);
  return response.data as Record<string, unknown>;
}
