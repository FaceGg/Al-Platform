import apiClient from "./client";

export async function listDatasets(projectId?: string) {
  const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const response = await apiClient.get(`/datasets${suffix}`);
  return response.data.items || [];
}

export async function getDatasetPreview(datasetId: string) {
  const response = await apiClient.get(`/datasets/${datasetId}/preview`);
  return response.data;
}
