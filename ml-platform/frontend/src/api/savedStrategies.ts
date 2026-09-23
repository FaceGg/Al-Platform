import apiClient from "./client";
import type { AutomaticStrategyDraft } from "../components/AutomaticAnnotationStrategyEditor";

export type SavedAnnotationStrategyPayload = AutomaticStrategyDraft;

export type SavedAnnotationStrategy = {
  id: string;
  project_id: string;
  name: string;
  payload: SavedAnnotationStrategyPayload;
  created_at: string | null;
  updated_at: string | null;
};

export async function listSavedStrategies(projectId: string): Promise<SavedAnnotationStrategy[]> {
  const response = await apiClient.get("/annotations/saved-strategies", { params: { project_id: projectId } });
  return (response.data?.items || []) as SavedAnnotationStrategy[];
}

export async function saveAnnotationStrategy(projectId: string, name: string, payload: SavedAnnotationStrategyPayload): Promise<SavedAnnotationStrategy> {
  const response = await apiClient.post("/annotations/saved-strategies", {
    project_id: projectId,
    name,
    payload,
  });
  return response.data as SavedAnnotationStrategy;
}
