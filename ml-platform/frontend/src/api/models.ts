import apiClient from "./client";

export type ModelArtifactOption = {
  id: string;
  name: string;
  type: "model";
  file_size?: number | null;
  format?: string | null;
  created_at?: string | null;
};

export async function listProjectModelArtifacts(projectId: string): Promise<ModelArtifactOption[]> {
  const response = await apiClient.get(`/projects/${encodeURIComponent(projectId)}/models`);
  return (response.data.items || response.data || []) as ModelArtifactOption[];
}
