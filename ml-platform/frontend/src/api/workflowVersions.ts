import apiClient from "./client";

export interface WorkflowVersionSummary {
  id: string;
  version: number;
  name: string;
  description: string;
  published_at: string | null;
}

export async function publishWorkflow(workflowId: string) {
  const response = await apiClient.post(`/workflows/${workflowId}/publish`);
  return response.data;
}

export async function listWorkflowVersions(workflowId: string): Promise<WorkflowVersionSummary[]> {
  const response = await apiClient.get(`/workflows/${workflowId}/versions`);
  return response.data.items || [];
}

export async function restoreWorkflowVersion(workflowId: string, version: number) {
  const response = await apiClient.post(`/workflows/${workflowId}/versions/${version}/restore`);
  return response.data;
}

export async function deleteWorkflowVersion(workflowId: string, version: number) {
  await apiClient.delete(`/workflows/${workflowId}/versions/${version}`);
}
