import apiClient from "./client";

export interface AnnotatorSubject { id: string; username: string; display_name?: string | null; status?: string; }
export interface SampleScope { kind: "ids"; sample_ids: string[]; }
export interface AssignmentRequest { annotator_ids: string[]; sample_scope: SampleScope; due_at?: string; }
export interface Assignment { id: string; task_id: string; annotator_subject_id: string; sample_scope: SampleScope; scope_hash: string; state: string; task_revision: number; }

export async function listAnnotatorSubjects(query = ""): Promise<AnnotatorSubject[]> {
  const response = await apiClient.get("/annotators", { params: { q: query || undefined } });
  const data = response.data as { items?: AnnotatorSubject[] } | AnnotatorSubject[];
  return Array.isArray(data) ? data : data.items || [];
}

export async function createAssignments(taskId: string, payload: AssignmentRequest, idempotencyKey = crypto.randomUUID()): Promise<{ items: Assignment[]; overlap_warning?: string | null }> {
  const response = await apiClient.post(`/annotation-tasks/${encodeURIComponent(taskId)}/assignments`, payload, {
    headers: {
      "X-Request-ID": crypto.randomUUID(),
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
