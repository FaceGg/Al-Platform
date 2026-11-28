import apiClient from "./client";

/** 发布治理 API（补齐路线第二批 S2b：B2-02/03/09/G2/G3，技术方案 §7.3）。
 *
 * 影子打分两种样本源：random_sample（样本池随机抽，记种子）/
 * traffic_mirror（镜像近期生产流量 sample_key——无流量或样本池无命中时
 * 后端 409 SHADOW_NO_TRAFFIC，诚实失败）。 */

export interface ShadowComparisonReport {
  id: string;
  champion_version_id: string | null;
  challenger_version_id: string | null;
  sample_source: string | null;
  sample_count: number;
  agreement_rate: number | null;
  detail: {
    comparable?: number;
    agreed?: number;
    grouped?: Record<string, { count: number; agreed: number }>;
    unmatched?: number;
    missing_reasons?: string[];
  };
  report_fingerprint: string;
  created_at: string | null;
}

export interface ReleaseCheck {
  check_key: string;
  verdict: string;
  threshold: number | null;
  observed: number | null;
}

export const registerChallenger = (projectId: string, deploymentId: string, modelVersionId: string) =>
  apiClient.post(`/projects/${projectId}/inference-deployments/${deploymentId}/challenger`, { model_version_id: modelVersionId });

export const retireChallenger = (projectId: string, deploymentId: string) =>
  apiClient.delete(`/projects/${projectId}/inference-deployments/${deploymentId}/challenger`);

export const runShadowBatch = (
  projectId: string,
  deploymentId: string,
  payload: { model_version_id: string; sample_source: "random_sample" | "traffic_mirror"; sample_size?: number },
) =>
  apiClient.post(`/projects/${projectId}/inference-deployments/${deploymentId}/shadow/runs`, payload);

export const listShadowReports = (projectId: string, deploymentId: string) =>
  apiClient.get(`/projects/${projectId}/inference-deployments/${deploymentId}/shadow/reports`)
    .then((res) => (res.data?.items || []) as ShadowComparisonReport[]);

export const shadowReportExportUrl = (projectId: string, deploymentId: string, reportId: string) =>
  `/api/projects/${projectId}/inference-deployments/${deploymentId}/shadow/reports/${reportId}/export.csv`;

export const grantPreauthorization = (
  projectId: string,
  payload: { deployment_id?: string | null; acceptance_gates_fingerprint: string; expires_at: string; max_releases?: number; note?: string | null },
) =>
  apiClient.post(`/projects/${projectId}/release-preauthorizations`, payload);

export const revokePreauthorization = (projectId: string, authId: string) =>
  apiClient.delete(`/projects/${projectId}/release-preauthorizations/${authId}`);

export const createReleaseRequest = (projectId: string, versionId: string, payload: {
  deployment_id: string;
  model_version_id: string;
  preauthorization_id?: string | null;
  strategy?: string;
  force_shadow_gate?: boolean;
}) =>
  apiClient.post(`/projects/${projectId}/model-versions/${versionId}/release-request`, payload)
    .then((res) => res.data as { approval_id: string; checks: ReleaseCheck[] });
