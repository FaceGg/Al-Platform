import apiClient from "./client";

/** S4 审计问答 API（补齐路线第二批 B2-01/B2-04，技术方案 §7）。
 *
 * 问数只走指标注册表（LLM 不生成 SQL，返回 answered/clarify/denied 三态）；
 * 审计报告十类模板、结构化证据 + 全局唯一引用编号 + 生成后校验。 */

export type AuditTemplateKey =
  | "quality" | "alerts" | "spc" | "drift" | "model"
  | "labeling" | "agent_actions" | "root_cause" | "process_window" | "disposition";

export const AUDIT_TEMPLATES: { key: AuditTemplateKey; zh: string; en: string }[] = [
  { key: "quality", zh: "质量总览", en: "Quality overview" },
  { key: "alerts", zh: "预警分析", en: "Alert analysis" },
  { key: "spc", zh: "SPC 过程", en: "SPC process" },
  { key: "drift", zh: "漂移", en: "Drift" },
  { key: "model", zh: "模型", en: "Model" },
  { key: "labeling", zh: "标注质量", en: "Labeling quality" },
  { key: "agent_actions", zh: "智能体动作", en: "Agent actions" },
  { key: "root_cause", zh: "根因", en: "Root cause" },
  { key: "process_window", zh: "过程窗口", en: "Process window" },
  { key: "disposition", zh: "处置", en: "Disposition" },
];

export interface AuditReport {
  id: string;
  template_key: string;
  status: string;
  content_markdown: string;
  evidence: unknown;
  citation_errors: unknown;
  created_at: string | null;
}

export interface MetricRegistryItem {
  name: string;
  footnote: string;
  source?: string;
}

export interface AskMetricsResult {
  status: "answered" | "clarify" | "denied";
  value?: unknown;
  metric?: string;
  footnote?: string;
  message?: string;
  candidates?: string[];
  known_metrics?: string[];
}

export interface TrustScore {
  score: number;
  grade: string;
  factors: Record<string, unknown>;
  computed_at: string | null;
}

export const askMetrics = (projectId: string, question: string) =>
  apiClient.post(`/projects/${projectId}/ask-metrics`, { question })
    .then((res) => res.data as AskMetricsResult);

export const listMetricRegistry = (projectId: string) =>
  apiClient.get(`/projects/${projectId}/metric-registry`)
    .then((res) => res.data as { items: MetricRegistryItem[]; custom_names: string[] });

export const createAuditReport = (projectId: string, templateKey: string, params: Record<string, unknown> = {}) =>
  apiClient.post(`/projects/${projectId}/audit-reports`, { template_key: templateKey, params })
    .then((res) => res.data as AuditReport);

export const listAuditReports = (projectId: string) =>
  apiClient.get(`/projects/${projectId}/audit-reports`)
    .then((res) => (res.data?.items || []) as AuditReport[]);

export const getAuditReport = (projectId: string, reportId: string) =>
  apiClient.get(`/projects/${projectId}/audit-reports/${reportId}`)
    .then((res) => res.data as AuditReport);

export const auditReportExportUrl = (projectId: string, reportId: string) =>
  `/api/projects/${projectId}/audit-reports/${reportId}/export.md`;

export const computeTrustScore = (projectId: string, versionId: string) =>
  apiClient.get(`/projects/${projectId}/model-versions/${versionId}/trust-score`)
    .then((res) => res.data as TrustScore);

export const listTrustScores = (projectId: string, versionId: string) =>
  apiClient.get(`/projects/${projectId}/model-versions/${versionId}/trust-scores`)
    .then((res) => (res.data?.items || []) as { score: number; grade: string; computed_at: string | null }[]);

export const cbpeEstimate = (projectId: string, versionId: string) =>
  apiClient.get(`/projects/${projectId}/model-versions/${versionId}/cbpe-estimate`)
    .then((res) => res.data as Record<string, unknown>);

export const refreshModelCard = (projectId: string, versionId: string) =>
  apiClient.post(`/projects/${projectId}/model-versions/${versionId}/model-card/refresh`)
    .then((res) => res.data as { card_id: string; sections: Record<string, unknown>; data_fingerprint_changed: boolean; approval_status: string });

export const explainSample = (projectId: string, versionId: string, row: Record<string, unknown>) =>
  apiClient.get(`/projects/${projectId}/model-versions/${versionId}/explain-sample`, { params: { row: JSON.stringify(row) } })
    .then((res) => res.data as Record<string, unknown>);
