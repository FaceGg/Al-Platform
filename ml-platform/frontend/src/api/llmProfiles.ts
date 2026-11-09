import apiClient from "./client";

export interface LLMProfile {
  id: string;
  name: string;
  provider: string;
  api_url: string;
  model_id: string;
  temperature: number | null;
  max_tokens: number | null;
  timeout_seconds: number;
  purpose_tags: string[];
  deployment: "cloud" | "private";
  is_default: boolean;
  /** 模型行启用开关：多模型可同时开启 */
  enabled?: boolean;
  /** 供应商组：同组 = 同一供应商下的多个模型；重复添加同名模板生成新组 */
  provider_group?: string | null;
  /** ZCode 风格模型配置：上下文窗口/最大输出/输入类型/能力/推理等级与映射 */
  model_config_json?: Record<string, unknown> | null;
  api_key_masked: string | null;
  created_at: string;
  updated_at: string;
}

export interface LLMProfilePayload {
  name: string;
  provider: string;
  api_url: string;
  api_key?: string;
  model_id: string;
  temperature?: number | null;
  max_tokens?: number | null;
  timeout_seconds?: number;
  purpose_tags?: string[];
  deployment: "cloud" | "private";
  is_default?: boolean;
  enabled?: boolean;
  model_config_json?: Record<string, unknown> | null;
  /** 供应商组：同组档案聚合为同一供应商（克隆/模板批量创建时传入源组） */
  provider_group?: string;
}

export interface LLMConnectivity {
  ok: boolean;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
}

export async function listLlmProfiles(): Promise<LLMProfile[]> {
  const res = await apiClient.get("/llm-profiles");
  return res.data;
}

export async function createLlmProfile(payload: LLMProfilePayload): Promise<LLMProfile> {
  const res = await apiClient.post("/llm-profiles", payload);
  return res.data;
}

export async function updateLlmProfile(id: string, payload: Partial<LLMProfilePayload>): Promise<LLMProfile> {
  const res = await apiClient.patch(`/llm-profiles/${id}`, payload);
  return res.data;
}

export async function deleteLlmProfile(id: string): Promise<void> {
  await apiClient.delete(`/llm-profiles/${id}`);
}

export async function testLlmProfile(id: string): Promise<LLMConnectivity> {
  const res = await apiClient.post(`/llm-profiles/${id}/test`);
  return res.data;
}
