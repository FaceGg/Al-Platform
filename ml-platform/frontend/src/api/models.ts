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
  /** 列约束（枚举值、范围二选一）：自动标注策略的取值同样受其约束 */
  enum_values?: Array<number | string>;
  min_value?: number;
  max_value?: number;
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
  } | null;
  selectable?: boolean;
  ineligible_reason?: string | null;
};

export async function listAnnotationModelVersions(projectId: string): Promise<AnnotationModelVersion[]> {
  const response = await apiClient.get(`/projects/${encodeURIComponent(projectId)}/annotation-model-versions`);
  return (response.data.items || response.data || []) as AnnotationModelVersion[];
}
