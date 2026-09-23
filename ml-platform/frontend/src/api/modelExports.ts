import apiClient from "./client";

export interface ModelExportRequest {
  model_version_id: string;
  export_kind: "predict" | "annotate";
  include_annotation?: boolean;
}

export interface ModelExport {
  id: string;
  status: "queued" | "running" | "ready" | "failed" | string;
  checksum?: string | null;
  signature?: string | null;
  download_url?: string | null;
  error_code?: string | null;
}

export async function createModelExport(projectId: string, payload: ModelExportRequest): Promise<ModelExport> {
  const response = await apiClient.post(`/projects/${encodeURIComponent(projectId)}/model-exports`, payload);
  return response.data as ModelExport;
}

export async function getModelExport(exportId: string): Promise<ModelExport> {
  const response = await apiClient.get(`/model-exports/${encodeURIComponent(exportId)}`);
  return response.data as ModelExport;
}

export async function downloadModelExport(exportId: string): Promise<Blob> {
  const response = await apiClient.get(`/model-exports/${encodeURIComponent(exportId)}/download`, {
    responseType: "blob",
  });
  return response.data as Blob;
}
