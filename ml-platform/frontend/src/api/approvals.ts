/** 统一四眼审批中心 API（补齐路线第二批 S1，技术方案 §2.3/§4.2）。 */

import apiClient from "./client";

function pageOf<T>(data: unknown): { items: T[]; total: number } {
  const body = (data ?? {}) as { items?: T[]; total?: number };
  return { items: Array.isArray(body.items) ? body.items : [], total: Number(body.total || 0) };
}

export type ApprovalType =
  | "disposition"
  | "retrain_proposal"
  | "model_release"
  | "recipe_change"
  | "exemption";

export type ApprovalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "invalidated"
  | "cancelled";

export type LegacySource =
  | "agent_task_review"
  | "model_version"
  | "model_card"
  | "skill_revision";

export interface ApprovalItem {
  id: string;
  project_id: string;
  type: ApprovalType;
  title: string;
  payload: Record<string, unknown>;
  status: ApprovalStatus;
  decision_note: string | null;
  created_by_id: string | null;
  decided_by_id: string | null;
  decided_at: string | null;
  expires_at: string | null;
  reminded_at: string | null;
  execution_status: "none" | "succeeded" | "failed";
  execution_ref: Record<string, unknown> | null;
  execution_error: string | null;
  trace_id: string;
  created_at: string | null;
  can_approve: boolean;
  trail?: Array<{
    action: string;
    result: string;
    actor: string;
    created_at: string | null;
    changes: Record<string, unknown>;
  }>;
}

export interface LegacyApprovalItem {
  source: LegacySource;
  ref_id: string;
  title: string;
  raw_status: string;
  status: string;
  initiator: string | null;
  decided_at: string | null;
  link: string;
  note: string | null;
}

export interface ApprovalListParams {
  status?: ApprovalStatus;
  type?: ApprovalType;
  mine?: "initiated" | "approvable";
  offset?: number;
  limit?: number;
}

export function listApprovals(projectId: string, params: ApprovalListParams = {}) {
  return apiClient
    .get(`/projects/${projectId}/approvals`, { params })
    .then((r) => pageOf<ApprovalItem>(r.data));
}

export function fetchApproval(projectId: string, approvalId: string) {
  return apiClient
    .get(`/projects/${projectId}/approvals/${approvalId}`)
    .then((r) => r.data as ApprovalItem);
}

export function createApproval(
  projectId: string,
  body: { type: ApprovalType; title: string; payload?: Record<string, unknown>; ttl_hours?: number },
) {
  return apiClient
    .post(`/projects/${projectId}/approvals`, body)
    .then((r) => r.data as ApprovalItem);
}

export function approveApproval(projectId: string, approvalId: string, note?: string) {
  return apiClient
    .post(`/projects/${projectId}/approvals/${approvalId}/approve`, { note: note ?? null })
    .then((r) => r.data as ApprovalItem);
}

export function rejectApproval(projectId: string, approvalId: string, note: string) {
  return apiClient
    .post(`/projects/${projectId}/approvals/${approvalId}/reject`, { note })
    .then((r) => r.data as ApprovalItem);
}

export function cancelApproval(projectId: string, approvalId: string) {
  return apiClient
    .post(`/projects/${projectId}/approvals/${approvalId}/cancel`)
    .then((r) => r.data as ApprovalItem);
}

export function listLegacyApprovals(projectId: string) {
  return apiClient
    .get(`/projects/${projectId}/approvals/legacy`)
    .then((r) => r.data as { items: LegacyApprovalItem[] });
}

export function fetchPendingApprovalCount() {
  return apiClient
    .get("/approvals/pending-count")
    .then((r) => (r.data as { count: number }).count);
}
