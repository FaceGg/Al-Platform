import apiClient from "./client";
import { createUuid } from "../utils/uuid";

export interface AnnotatorSubject { id: string; username: string; display_name?: string | null; email?: string | null; status?: string; }
export interface SampleScope {
  kind: "ids" | "frozen_task_scope";
  sample_ids?: string[];
  sample_count?: number;
  scope_hash?: string;
  task_revision?: number;
}
export interface AssignmentRequest { annotator_ids: string[]; sample_scope: SampleScope; due_at?: string; }
export interface Assignment { id: string; task_id: string; annotator_subject_id: string; sample_scope: SampleScope; scope_hash: string; state: string; task_revision: number; }

export async function listAnnotatorSubjects(query = "", projectId?: string): Promise<AnnotatorSubject[]> {
  const response = await apiClient.get("/annotators", { params: { q: query || undefined, project_id: projectId || undefined } });
  const data = response.data as { items?: AnnotatorSubject[] } | AnnotatorSubject[];
  return Array.isArray(data) ? data : data.items || [];
}

export interface AnnotatorProjectGrant { project_id: string; status: string; }

export async function listAnnotatorProjectGrants(subjectId: string): Promise<AnnotatorProjectGrant[]> {
  const response = await apiClient.get(`/admin/annotators/${encodeURIComponent(subjectId)}/grants`);
  const data = response.data as { items?: AnnotatorProjectGrant[] } | AnnotatorProjectGrant[];
  return Array.isArray(data) ? data : data.items || [];
}

export async function grantAnnotatorProject(projectId: string, subjectId: string): Promise<void> {
  await apiClient.post(`/internal/projects/${encodeURIComponent(projectId)}/annotators/${encodeURIComponent(subjectId)}/grant`);
}

export async function revokeAnnotatorProject(projectId: string, subjectId: string): Promise<void> {
  await apiClient.delete(`/internal/projects/${encodeURIComponent(projectId)}/annotators/${encodeURIComponent(subjectId)}/grant`);
}

export async function createAssignments(taskId: string, payload: AssignmentRequest, idempotencyKey = createUuid()): Promise<{ items: Assignment[]; overlap_warning?: string | null }> {
  const response = await apiClient.post(`/annotation-tasks/${encodeURIComponent(taskId)}/assignments`, payload, {
    headers: {
      "X-Request-ID": createUuid(),
      "Idempotency-Key": idempotencyKey,
    },
  });
  return response.data as { items: Assignment[]; overlap_warning?: string | null };
}

export async function listTaskAssignments(taskId: string): Promise<Assignment[]> {
  const response = await apiClient.get(`/annotation-tasks/${encodeURIComponent(taskId)}/assignments`);
  const data = response.data as { items?: Assignment[] } | Assignment[];
  return Array.isArray(data) ? data : data.items || [];
}
