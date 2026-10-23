import apiClient from "./client";

export interface KBBinding {
  id: string;
  kb_id: string;
  kb_name: string;
  is_system: boolean;
  enabled: boolean;
  scope_projects: string[];
  scope_chat: boolean;
  scope_agent_s1: boolean;
  retrieval_top_k: number;
  retrieval_min_score: number;
  retrieval_trigger: string;
  sync_receive_experience: boolean;
  sync_experience_min_confidence: number;
  sync_human_review: string;
  doc_count: number;
}

export interface ExperienceEntry {
  id: string;
  domain: string;
  situation: string;
  lesson: string;
  action: string;
  confidence: number;
  origin: string;
  status: string;
  hit_count: number;
  human_note: string | null;
  source_tasks: string[];
}

export async function listBindings(): Promise<KBBinding[]> {
  const res = await apiClient.get("/knowledge-center/bindings");
  return res.data;
}

export async function patchBinding(
  id: string,
  changes: Partial<KBBinding>
): Promise<KBBinding> {
  const res = await apiClient.patch(`/knowledge-center/bindings/${id}`, changes);
  return res.data;
}

export async function listExperience(params?: {
  status?: string;
  domain?: string;
}): Promise<ExperienceEntry[]> {
  const res = await apiClient.get("/knowledge-center/experience", { params });
  return res.data;
}

export async function retireExperience(id: string): Promise<void> {
  await apiClient.post(`/knowledge-center/experience/${id}/retire`);
}

export async function annotateExperience(id: string, note: string): Promise<void> {
  await apiClient.post(`/knowledge-center/experience/${id}/note`, { note });
}
