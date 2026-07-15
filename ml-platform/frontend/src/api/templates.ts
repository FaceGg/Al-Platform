import apiClient from "./client";

export interface TemplateParameter {
  key: string;
  label: string;
  type: "int" | "float" | "text";
  default: number | string;
  required: boolean;
}

export interface IndustrialTemplateDetail {
  id: string;
  name: string;
  description: string;
  scenario: string;
  task_type: string;
  target_column: string;
  required_columns: string[];
  parameters: TemplateParameter[];
}

export interface InstantiateTemplateRequest {
  project_id: string;
  dataset_artifact_id: string;
  parameters: Record<string, number | string>;
}

export interface InstantiateTemplateResponse {
  workflow_id: string;
  template_id: string;
  dataset_artifact_id: string;
}

export async function getTemplate(templateId: string): Promise<IndustrialTemplateDetail> {
  const response = await apiClient.get(`/templates/${templateId}`);
  return response.data;
}

export async function instantiateTemplate(
  templateId: string,
  request: InstantiateTemplateRequest,
): Promise<InstantiateTemplateResponse> {
  const response = await apiClient.post(`/templates/${templateId}/instantiate`, request);
  return response.data;
}
