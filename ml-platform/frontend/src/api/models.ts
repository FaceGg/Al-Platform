import apiClient from "./client";

export type ModelArtifactOption = {
  id: string;
  name: string;
  type: "model";
  file_size?: number | null;
  format?: string | null;
  created_at?: string | null;
};

export type AnnotationOutputColumn = {
  machine_key: string;
  display_name: string;
  value_type: "string" | "int" | "float";
  required: boolean;
};

export type AnnotationModelVersion = {
  id: string;
  registered_model_id: string;
  model_name: string;
  version_number: number;
  algorithm: string;
  feature_schema: Array<{ name: string; dtype: string }>;
  output_contract: {
    model_version_id: string;
    registered_model_id: string;
    model_name: string;
    version_number: number;
    columns: AnnotationOutputColumn[];
    contract_hash: string;
  };
};

export async function listProjectModelArtifacts(projectId: string): Promise<ModelArtifactOption[]> {
  const response = await apiClient.get(`/projects/${encodeURIComponent(projectId)}/models`);
  return (response.data.items || response.data || []) as ModelArtifactOption[];
}

export async function listAnnotationModelVersions(projectId: string): Promise<AnnotationModelVersion[]> {
  const response = await apiClient.get(`/projects/${encodeURIComponent(projectId)}/annotation-model-versions`);
  return (response.data.items || response.data || []) as AnnotationModelVersion[];
}
