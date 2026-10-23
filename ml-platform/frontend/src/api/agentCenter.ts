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

export interface AgentRunDetail extends AgentRunItem {
  dataset_artifact_id: string | null;
  llm_model_id: string | null;
  token_budget: number | null;
  memory_json: {
    rounds?: {
      round?: number;
      s2_attempts?: { attempt?: number; error?: string; detail?: unknown; ok?: boolean }[];
      verdict?: string;
      hints?: string[];
    }[];
    gate_warnings?: string[];
    resume?: Record<string, unknown>;
  };
  result_json: Record<string, unknown>;
}

export async function listAgentRuns(limit = 50): Promise<AgentRunItem[]> {
  const response = await apiClient.get("/agent/runs", { params: { limit } });
  return Array.isArray(response.data) ? response.data : [];
}

export async function getAgentRun(runId: string): Promise<AgentRunDetail> {
  const response = await apiClient.get(`/agent/runs/${runId}`);
  return response.data;
}

export interface AgentRunCreatePayload {
  dataset_artifact_id: string;
  target_column: string;
  project_id?: string | null;
  llm_profile_id?: string | null;
  llm_model_id?: string | null;
  token_budget?: number | null;
  step_by_step?: boolean;
  guidance: {
    analysis?: { column_notes?: { column: string; note: string }[]; prompts?: string[] };
    feature?: {
      data_shape?: "tabular" | "waveform" | "mixed";
      must_keep?: string[];
      suggest_drop?: { column: string; reason?: string }[];
      prompts?: string[];
    };
    modeling?: { algorithm_whitelist?: string[]; param_hints?: Record<string, number | string>; prompts?: string[] };
    evaluation?: { metric_gates?: Record<string, number>; review_focus?: string[] };
  };
}

export async function createAgentRun(payload: AgentRunCreatePayload): Promise<AgentRunDetail> {
  const response = await apiClient.post("/agent/runs", payload);
  return response.data;
}

export interface DatasetProfileColumn {
  name: string;
  base_name: string;
  semantic: string | null;
  missing_rate: number;
  cardinality: number;
  constant: boolean;
}

export interface DatasetProfile {
  row_count: number;
  column_count: number;
  columns: DatasetProfileColumn[];
  mutual_info_top: Array<{ column: string; mi: number }>;
  target: {
    distribution: Record<string, number>;
    imbalance_ratio: number | null;
  } | null;
}

export async function fetchDatasetProfile(
  datasetId: string,
  target?: string,
  projectId?: string
): Promise<DatasetProfile> {
  const response = await apiClient.get(`/agent/datasets/${datasetId}/profile`, {
    params: { target: target || undefined, project_id: projectId || undefined },
  });
  return response.data;
}

export async function fixateRecipe(
  runId: string,
  name?: string
): Promise<{ recipe_id: string; version: number; created: boolean }> {
  const response = await apiClient.post("/agent/recipes/fixate", { run_id: runId, name });
  return response.data;
}

export async function listRecipeVersions(recipeId: string): Promise<
  Array<{
    version: number;
    status: string;
    change_note: string | null;
    created_at: string | null;
    baseline_metrics: Record<string, number>;
  }>
> {
  const response = await apiClient.get(`/agent/recipes/${recipeId}/versions`);
  return response.data;
}

export async function rollbackRecipe(
  recipeId: string,
  toVersion: number
): Promise<{ new_version: number }> {
  const response = await apiClient.post(`/agent/recipes/${recipeId}/rollback`, {
    to_version: toVersion,
  });
  return response.data;
}

export async function listPipelineRecipes(limit = 100): Promise<PipelineRecipeItem[]> {
  const response = await apiClient.get("/agent/recipes", { params: { limit } });
  return Array.isArray(response.data) ? response.data : [];
}
