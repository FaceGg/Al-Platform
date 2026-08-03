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

export async function downloadDatasetArtifact(datasetId: string, fallbackName = "dataset.csv") {
  const response = await apiClient.get(`/datasets/${datasetId}/download`, { responseType: "blob" });
  const disposition = String(response.headers?.["content-disposition"] || "");
  const encodedName = disposition.match(/filename\*=utf-8''([^;]+)/i)?.[1];
  const filename = encodedName ? decodeURIComponent(encodedName) : fallbackName;
  const href = URL.createObjectURL(response.data as Blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(href);
}
