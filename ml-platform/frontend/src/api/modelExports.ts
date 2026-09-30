import apiClient from "./client";
import { createUuid } from "../utils/uuid";

export type ModelExportKind = "predict" | "annotate";

export interface ModelExportRequest {
  model_version_id: string;
  export_kind: ModelExportKind;
}

export interface ModelExport {
  id: string;
  operation_id?: string | null;
  status: "queued" | "running" | "completed" | "failed" | string;
  manifest_sha256?: string | null;
  error?: { code?: string | null; message?: string | null } | null;
}

export async function createModelExport(versionId: string, payload: ModelExportRequest): Promise<ModelExport> {
  // The backend packages annotation strategy files only when a revision is
  // bound; annotate exports pin the version's current payload to revision 0.
  const body: Record<string, unknown> = {
    model_version_id: payload.model_version_id,
    include_runtime: true,
  };
  if (payload.export_kind === "annotate") {
    body.annotation_task_revision = 0;
  }
  const response = await apiClient.post(`/model-versions/${encodeURIComponent(versionId)}/exports`, body, {
    headers: { "Idempotency-Key": createUuid() },
  });
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
