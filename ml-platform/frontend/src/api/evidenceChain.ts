import apiClient from "./client";

/** 闭环证据总览与证据链导出 API（补齐路线第一批 F2b，B1-12/E21，技术方案 §9.9）。 */

export type StageStatus = "complete" | "pending" | "missing" | "not_supported" | "not_applicable";

export interface StageEvidence {
  label: string;
  ref_type: string;
  ref_id: string | null;
}

export interface EvidenceStage {
  key: string;
  title: string;
  title_en: string;
  status: StageStatus;
  note: string;
  evidence: StageEvidence[];
}

export interface LaunchCheck {
  key: string;
  title: string;
  title_en: string;
  status: "pass" | "fail";
  detail: string;
  value?: unknown;
}

export interface EvidenceModelVersion {
  id: string;
  version_number: number;
  model_name: string | null;
  source_kind: string;
  algorithm: string;
  framework: string;
  approval_status: string;
  lifecycle_state: string;
  training_job_id: string | null;
  dataset_version_id: string | null;
}

export interface EvidenceOverview {
  model_version: EvidenceModelVersion;
  stages: EvidenceStage[];
  checks: LaunchCheck[];
  summary: Record<StageStatus, number>;
  checks_passed: number;
  checksum_verified: boolean;
  generated_at: string;
  archived_check?: { id: string; created_at: string; checks_passed: number } | null;
  archived_check_id?: string;
}

export interface EvidenceExportResult {
  artifact_id: string;
  name: string;
  file_size: number;
  sha256: string | null;
  file_count: number;
  include_audit: boolean;
}

export const STAGE_STATUS_LABELS = {
  zh: {
    complete: "完成", pending: "待发生", missing: "缺失",
    not_supported: "未接入", not_applicable: "不适用",
  } as Record<StageStatus, string>,
  en: {
    complete: "Complete", pending: "Pending", missing: "Missing",
    not_supported: "Not supported yet", not_applicable: "Not applicable",
  } as Record<StageStatus, string>,
};

export const STAGE_STATUS_COLOR: Record<StageStatus, string> = {
  complete: "green", pending: "gold", missing: "red",
  not_supported: "default", not_applicable: "default",
};

/** 环节下钻目标：按依据类型给出前端已有页面的路径。没有对应页面的类型返回 null
 * （不给链接）——宁可不可点，也不做点了落空的死链。 */
export function evidenceRefPath(ref: Pick<StageEvidence, "ref_type" | "ref_id">): string | null {
  if (!ref.ref_id) return null;
  switch (ref.ref_type) {
    case "dataset_version":
      return "/data";
    case "annotation_task":
    case "annotation_strategy_artifact":
      return "/data-annotation";
    case "training_job":
      return "/training";
    case "inference_deployment":
      return "/models";
    case "demo_loop_config":
      return "/demo-loop";
    default:
      return null;
  }
}

export async function getEvidenceOverview(projectId: string, versionId: string): Promise<EvidenceOverview> {
  const res = await apiClient.get(`/projects/${projectId}/model-versions/${versionId}/evidence-overview`);
  return res.data;
}

export async function archiveEvidenceCheck(projectId: string, versionId: string): Promise<EvidenceOverview> {
  const res = await apiClient.post(`/projects/${projectId}/model-versions/${versionId}/evidence-checks`);
  return res.data;
}

export async function exportEvidence(
  projectId: string, scope: "alert" | "model_version", targetId: string,
): Promise<EvidenceExportResult> {
  const res = await apiClient.post(`/projects/${projectId}/evidence-exports`, { scope, target_id: targetId });
  return res.data;
}

export async function downloadEvidence(projectId: string, artifactId: string): Promise<Blob> {
  const res = await apiClient.get(`/projects/${projectId}/evidence-exports/${artifactId}/download`, {
    responseType: "blob",
  });
  return res.data as Blob;
}
