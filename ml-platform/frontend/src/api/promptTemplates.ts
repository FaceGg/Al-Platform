import apiClient from "./client";

export interface PromptTemplate {
  id: string;
  name: string;
  stage: string;
  content: string;
  project_id: string | null;
  usage_count: number;
}

export async function listPromptTemplates(params?: {
  stage?: string;
  project_id?: string;
}): Promise<PromptTemplate[]> {
  const response = await apiClient.get("/prompt-templates", { params });
  return response.data;
}

export async function createPromptTemplate(payload: {
  name: string;
  stage: string;
  content: string;
  project_id?: string | null;
}): Promise<PromptTemplate> {
  const response = await apiClient.post("/prompt-templates", payload);
  return response.data;
}

export async function deletePromptTemplate(id: string): Promise<void> {
  await apiClient.delete(`/prompt-templates/${id}`);
}

export async function usePromptTemplate(id: string): Promise<PromptTemplate> {
  const response = await apiClient.post(`/prompt-templates/${id}/use`);
  return response.data;
}

export const PROMPT_STAGES = ["analysis", "feature", "modeling", "evaluation"] as const;
