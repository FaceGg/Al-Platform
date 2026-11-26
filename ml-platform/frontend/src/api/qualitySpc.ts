import apiClient from "./client";

/** SPC 分析与漂移监控 API（补齐路线第一批 F4，B1-06/B1-09，技术方案 §9C）。 */

export type SpcChartKind = "xbar_r" | "xbar_s" | "i_mr" | "p" | "np" | "c" | "u";
export type SpcSource = "dataset" | "inference";

export interface SpcField {
  name: string;
  label?: string;
  dtype?: string;
  numeric: boolean;
}

export interface SpcPoint {
  index: number;
  value: number;
  violations: number[];
  ucl: number | null;
  lcl: number | null;
  sample_key: string | null;
  occurred_at: string | null;
}

export interface SpcChartPayload {
  kind: string;
  center: number;
  ucl: number;
  lcl: number;
  sigma: number;
  in_control_count: number;
  in_control_rate: number | null;
  notes: string[];
  points: SpcPoint[];
}

export interface SpcCapability {
  count: number;
  mean: number;
  usl: number | null;
  lsl: number | null;
  target: number | null;
  within_sigma: number;
  overall_sigma: number;
  within_sigma_source: "range" | "baseline" | "overall";
  cp: number | null;
  cpk: number | null;
  pp: number | null;
  ppk: number | null;
  cpm: number | null;
  cr: number | null;
  sigma_level: number | null;
  ppm: number | null;
}

export interface SpcViolation {
  chart: string;
  rule: number;
  index: number;
  value: number;
  sample_key: string | null;
  occurred_at: string | null;
}

export interface SpcAnalysisRequest {
  source: SpcSource;
  field: string;
  chart: SpcChartKind;
  dataset_version_id?: string | null;
  scene_id?: string | null;
  station_id?: string | null;
  subgroup_size?: number;
  row_from?: number | null;
  row_to?: number | null;
  defect_field?: string | null;
  hours?: number;
  usl?: number | null;
  lsl?: number | null;
  target?: number | null;
  use_scene_spec?: boolean;
  rules?: number[];
  raise_alerts?: boolean;
}

export interface SpcAnalysisResult {
  chart_kind: SpcChartKind;
  source: SpcSource;
  field: string;
  sample_count: number;
  subgroup_size: number | null;
  subgroup_count: number | null;
  spec: { usl: number | null; lsl: number | null; target: number | null; unit?: string | null; source: string };
  charts: Record<string, SpcChartPayload>;
  capability: SpcCapability | null;
  histogram: { edges: number[]; counts: number[] };
  violations: SpcViolation[];
  violation_count: number;
  alerts_raised: number;
  notes: string[];
  generated_at: string;
}

export async function getSpcFields(projectId: string, source: SpcSource, datasetVersionId?: string): Promise<SpcField[]> {
  const res = await apiClient.get(`/projects/${projectId}/spc/fields`, {
    params: source === "dataset" ? { source, dataset_version_id: datasetVersionId } : { source },
  });
  return res.data?.fields ?? [];
}

export async function analyzeSpc(projectId: string, request: SpcAnalysisRequest): Promise<SpcAnalysisResult> {
  const res = await apiClient.post(`/projects/${projectId}/spc/analyze`, request);
  return res.data;
}

// ------------------------------------------------------------------
// 漂移监控
// ------------------------------------------------------------------

export type DriftLevel = "severe" | "watch" | "stable" | "insufficient";
export type DriftSignalKind = "feature_psi" | "dq_missing" | "dq_constant";

export interface DriftDeploymentItem {
  id: string;
  name: string;
  model_version_id: string;
  has_baseline: boolean;
  latest: DriftReport | null;
}

export interface DriftReport {
  id: string;
  project_id: string;
  deployment_id: string | null;
  model_version_id: string | null;
  deployment_name?: string;
  started_at: string | null;
  ended_at: string | null;
  level: DriftLevel;
  sample_count: number;
  summary: Record<string, unknown>;
  proposal_at: string | null;
  created_at: string | null;
}

export interface DriftReportDetail extends DriftReport {
  features: Array<{
    feature_name: string;
    signal_kind: DriftSignalKind;
    value: number;
    threshold: number;
    level: string;
    detail: Record<string, unknown>;
  }>;
  not_wired: string[];
}

export async function getDriftDeployments(projectId: string): Promise<DriftDeploymentItem[]> {
  const res = await apiClient.get(`/projects/${projectId}/drift/deployments`);
  return res.data?.items ?? [];
}

export interface DriftReportPage {
  items: DriftReport[];
  total: number;
  page: number;
  page_size: number;
}

export async function getDriftReports(
  projectId: string, deploymentId?: string, page = 1, pageSize = 20,
): Promise<DriftReportPage> {
  const res = await apiClient.get(`/projects/${projectId}/drift/reports`, {
    params: { deployment_id: deploymentId || undefined, page, page_size: pageSize },
  });
  return {
    items: Array.isArray(res.data?.items) ? res.data.items : [],
    total: Number(res.data?.total || 0),
    page: Number(res.data?.page || 1),
    page_size: Number(res.data?.page_size || 20),
  };
}

export async function getDriftReport(projectId: string, reportId: string): Promise<DriftReportDetail> {
  const res = await apiClient.get(`/projects/${projectId}/drift/reports/${reportId}`);
  return res.data;
}

export async function proposeRetrain(projectId: string, reportId: string): Promise<{ notified: number }> {
  const res = await apiClient.post(`/projects/${projectId}/drift/reports/${reportId}/propose-retrain`);
  return res.data;
}

export async function triggerDriftScan(projectId: string): Promise<{ scanned: number; levels: Record<string, number> }> {
  const res = await apiClient.post(`/projects/${projectId}/drift/scan`);
  return res.data;
}

export const DRIFT_LEVEL_LABELS = {
  zh: { severe: "严重漂移", watch: "关注", stable: "稳定", insufficient: "样本不足" } as Record<DriftLevel, string>,
  en: { severe: "Severe drift", watch: "Watch", stable: "Stable", insufficient: "Insufficient samples" } as Record<DriftLevel, string>,
};

export const DRIFT_LEVEL_COLOR: Record<DriftLevel, string> = {
  severe: "red", watch: "gold", stable: "green", insufficient: "default",
};

export const DRIFT_SIGNAL_LABELS = {
  zh: { feature_psi: "特征分布漂移", dq_missing: "缺失率过高", dq_constant: "取值集中于单一分箱" } as Record<DriftSignalKind, string>,
  en: { feature_psi: "Feature PSI", dq_missing: "Missing ratio", dq_constant: "Single-bin concentration" } as Record<DriftSignalKind, string>,
};
