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
