import apiClient from "./client";

/** S3 标注质量 API（补齐路线第二批 B2-05/06/G4，技术方案 §8.3）。
 *
 * 一致性轮（≥2 标注员盲标同批样本 → κ 计算 → 分歧自动进仲裁）；盲标提交
 * 身份一律绑定登录用户（后端强制，请求体不含 subject）；主动学习选样的
 * frame_rows 由调用方冻结传入。 */

export interface ActiveLearningSelection {
  id: string;
  strategy: Record<string, unknown>;
  budget_per_round: number;
  selected_count: number;
  strategy_stats: Record<string, unknown>;
  created_at: string | null;
}

export interface LabelArbitration {
  id: string;
  round_id: string;
  sample_id: string;
  conflict: unknown;
  status: string;
  decision_values: Record<string, unknown> | null;
  arbiter_id: string | null;
}

export interface LabelQualityGate {
  status?: string;
  kappa?: number | null;
  threshold?: number | null;
  [key: string]: unknown;
}

export const listActiveLearningSelections = (projectId: string) =>
  apiClient.get(`/projects/${projectId}/active-learning/selections`)
    .then((res) => (res.data?.items || []) as ActiveLearningSelection[]);

export const createActiveLearningSelection = (
  projectId: string,
  payload: {
    strategy: Record<string, unknown>;
    budget_initial?: number;
    budget_per_round?: number;
    frame_rows: Record<string, unknown>[];
    feature_columns?: string[];
  },
) =>
  apiClient.post(`/projects/${projectId}/active-learning/selections`, payload)
    .then((res) => res.data as { id: string; selected_sample_ids: string[]; strategy_stats: Record<string, unknown> });

export const openConsistencyRound = (
  projectId: string,
  payload: { annotator_subject_ids: string[]; sample_ids: string[]; task_id?: string | null; kappa_threshold?: number },
) =>
  apiClient.post(`/projects/${projectId}/consistency-rounds`, payload)
    .then((res) => res.data as { id: string; status: string });

export const submitBlindLabel = (
  projectId: string,
  roundId: string,
  payload: { sample_id: string; values: Record<string, unknown> },
) =>
  apiClient.put(`/projects/${projectId}/consistency-rounds/${roundId}/labels`, payload)
    .then((res) => res.data as { id: string });

export const computeRoundKappa = (projectId: string, roundId: string) =>
  apiClient.post(`/projects/${projectId}/consistency-rounds/${roundId}/compute`)
    .then((res) => res.data as { kappa_pairwise: unknown; kappa_average: unknown; status: string });

export const listArbitrations = (projectId: string, status?: string) =>
  apiClient.get(`/projects/${projectId}/arbitrations`, { params: status ? { status } : undefined })
    .then((res) => (res.data?.items || []) as LabelArbitration[]);

export const decideArbitration = (
  projectId: string,
  arbitrationId: string,
  payload: { decision_values: Record<string, unknown>; note?: string | null },
) =>
  apiClient.post(`/projects/${projectId}/arbitrations/${arbitrationId}/decide`, payload)
    .then((res) => res.data as { id: string; status: string });

export const labelQualityGate = (projectId: string) =>
  apiClient.get(`/projects/${projectId}/label-quality/gate`)
    .then((res) => res.data as LabelQualityGate);

export const createPseudoLabelBatch = (
  projectId: string,
  payload: { candidates: { sample_key: string; label: string; confidence: number }[]; threshold?: number; quota_multiplier?: number; dataset_version_id?: string | null; model_version_id?: string | null },
) =>
  apiClient.post(`/projects/${projectId}/pseudo-labels/batches`, payload)
    .then((res) => res.data as { id: string; selected_count: number });

export const pseudoCredentialExportUrl = (projectId: string, batchId: string) =>
  `/api/projects/${projectId}/pseudo-labels/batches/${batchId}/credential.csv`;
