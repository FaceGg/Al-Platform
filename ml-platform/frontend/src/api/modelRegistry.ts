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

function normalizeList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === "object" && Array.isArray((data as { items?: unknown }).items)) {
    return (data as { items: T[] }).items;
  }
  return [];
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
