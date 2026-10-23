import apiClient from "./client";

export interface AgentRunItem {
  id: string;
  project_id: string | null;
  project_name: string | null;
  target_column: string | null;
  status: string;
  current_stage: string;
  round_count: number;
  token_used: number;
  error_code: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PipelineRecipeItem {
  id: string;
  project_id: string | null;
  project_name: string | null;
  name: string;
  domain: string | null;
  target_column: string | null;
  current_version: number;
  version_status: string | null;
  change_note: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export async function listAgentRuns(limit = 50): Promise<AgentRunItem[]> {
  const response = await apiClient.get("/agent/runs", { params: { limit } });
  return Array.isArray(response.data) ? response.data : [];
}

export async function listPipelineRecipes(limit = 100): Promise<PipelineRecipeItem[]> {
  const response = await apiClient.get("/agent/recipes", { params: { limit } });
  return Array.isArray(response.data) ? response.data : [];
}
