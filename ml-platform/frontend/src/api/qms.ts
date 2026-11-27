import apiClient from "./client";

/** 质量体系 QMS API（补齐路线第三批 B3，技术方案 §3）。
 *
 * 领域口径（IATF 16949 / 8D / MSA）待质量专家评审；最小页面骨架（列表+详情+表单），
 * 空态引导见各页。
 */

export type NcrStage = "draft" | "analysis" | "action" | "verification" | "closed" | "rejected";
export type CaseStatus = "open" | "monitoring" | "closed";
export type CaseSeverity = "low" | "medium" | "high" | "critical";
export type ReportPeriod = "daily" | "weekly" | "monthly";
export type GrrGrade = "acceptable" | "conditional" | "unacceptable";

export interface QmsNcr {
  id: string; code: string; title: string; stage: NcrStage;
  verification_cycles: number;
}
export interface QmsNcrDetail extends QmsNcr {
  reject_reason: string | null;
  source_alert_id: string | null;
  closed_at: string | null;
  actions: { phase: string; action: string; created_at: string | null }[];
}

export interface QmsD8 {
  id: string; code: string; title: string; current_step: number;
  d6_passed: boolean; closed_at: string | null;
}
export interface QmsD8Detail extends QmsD8 {
  steps: Record<string, { content?: Record<string, unknown>; confirmed_at?: string; drafted?: boolean }>;
  ncr_id: string | null; case_id: string | null;
}

export interface QmsCase {
  id: string; code: string; title: string; severity: CaseSeverity; status: CaseStatus;
}
export interface QmsCaseDetail extends QmsCase {
  keywords: string | null; source_alert_id: string | null; closed_at: string | null;
  links: { object_type: string; object_id: string }[];
}

export interface QmsKnowledgeEntry {
  id: string; defect_code: string; symptom: string; root_cause: string | null;
}

export interface QmsSymptomHit {
  match_score: number; match_reason: string;
  defect_code: string; root_cause: string | null;
}

export interface QmsTraceResult {
  sample_key: string;
  trace_links: { dataset_version_id: string | null; batch_no: string | null }[];
  inference_results: { id: string; predicted_label: unknown; channel: string; occurred_at: string | null }[];
  alerts: { id: string; title: string; severity: string; status: string }[];
  ncr_ids: string[];
}

export interface QmsTraceBatch {
  batch_no: string; sample_count: number; sample_keys: string[];
  dataset_version_ids: string[];
  inference_results: { id: string; predicted_label: unknown; sample_key: string | null; channel: string }[];
  alerts: { id: string; title: string; severity: string; status: string }[];
  ncr_ids: string[];
}

export interface QmsReport {
  id: string; period: ReportPeriod; period_key: string;
  generated_by: "scheduler" | "manual";
  content: {
    window?: string[]; alert_total: number; ng_rate: number | null;
    cpk_pass_rate: number | null; top_defects: unknown[]; ncr_open: number;
    footnote?: string;
  };
}

export interface QmsControlPlan {
  id: string; code: string; version: number; status: "active" | "archived";
  tightening_multiplier: number;
  quality_points: { name: string; sample?: number }[];
}

export interface QmsPlanDiff {
  from_version: number | null; to_version: number;
  multiplier_before: number; multiplier_after: number;
  quality_point_changes: { quality_point: string; before: unknown; after: unknown }[];
}

export interface QmsMsaStudy {
  id: string; name: string; part_count: number; operator_count: number;
  replicates: number; grr_percent: number | null; ndc: number | null;
  grade: GrrGrade | null;
}

export interface QmsFmeaItem {
  failure_mode: string; effect: string; severity: number; occurrence: number;
  detection: number; prevention: string; rpn: number;
}
export interface QmsFmea { id: string; name: string; items: QmsFmeaItem[]; }

export interface QmsSupplier { id: string; code: string; name: string; status: "active" | "disabled"; }
export interface QmsIqcRecord {
  id: string; supplier_id: string; arrival_count: number;
  inspected_count: number; defect_count: number; scar_id: string | null;
}
export interface QmsScar { id: string; iqc_record_id: string; cause: string | null; closed_at: string | null; }

const base = (projectId: string) => `/projects/${projectId}/qms`;

// ---- NCR（B3-04） ----
export async function listNcr(projectId: string): Promise<QmsNcr[]> {
  const res = await apiClient.get(`${base(projectId)}/ncr-capa`);
  return res.data?.items ?? [];
}
export async function getNcr(projectId: string, id: string): Promise<QmsNcrDetail> {
  const res = await apiClient.get(`${base(projectId)}/ncr-capa/${id}`);
  return res.data;
}
export async function createNcr(projectId: string, body: {
  code: string; title: string; source_alert_id?: string | null;
}): Promise<{ id: string; stage: string }> {
  const res = await apiClient.post(`${base(projectId)}/ncr-capa`, body);
  return res.data;
}
export async function transitionNcr(projectId: string, id: string): Promise<{ stage: string }> {
  const res = await apiClient.post(`${base(projectId)}/ncr-capa/${id}/transition`, {});
  return res.data;
}
export async function rejectNcr(projectId: string, id: string, reason: string): Promise<{ stage: string }> {
  const res = await apiClient.post(`${base(projectId)}/ncr-capa/${id}/reject`, { reason });
  return res.data;
}

// ---- 8D（B3-03） ----
export async function listD8(projectId: string): Promise<QmsD8[]> {
  const res = await apiClient.get(`${base(projectId)}/d8`);
  return res.data?.items ?? [];
}
export async function getD8(projectId: string, id: string): Promise<QmsD8Detail> {
  const res = await apiClient.get(`${base(projectId)}/d8/${id}`);
  return res.data;
}
export async function createD8(projectId: string, body: {
  code: string; title: string; ncr_id?: string | null; case_id?: string | null;
}): Promise<{ id: string; current_step: number }> {
  const res = await apiClient.post(`${base(projectId)}/d8`, body);
  return res.data;
}
export async function advanceD8(projectId: string, id: string, body: {
  step_content?: Record<string, unknown>; d6_passed?: boolean | null;
}): Promise<{ current_step: number; d6_passed: boolean }> {
  const res = await apiClient.post(`${base(projectId)}/d8/${id}/advance`, body);
  return res.data;
}
export async function draftD8(projectId: string, id: string, context: string): Promise<{ drafted: boolean; via: string }> {
  const res = await apiClient.post(`${base(projectId)}/d8/${id}/draft-llm`, { context });
  return res.data;
}
export async function closeD8(projectId: string, id: string): Promise<void> {
  await apiClient.post(`${base(projectId)}/d8/${id}/close`, {});
}
export async function exportD8Evidence(projectId: string, id: string): Promise<{ artifact_id: string; download: string }> {
  const res = await apiClient.post(`${base(projectId)}/d8/${id}/evidence`, {});
  return res.data;
}

// ---- 案例（B3-07） ----
export async function listCases(projectId: string, params?: {
  status?: string; severity?: string; keyword?: string;
}): Promise<QmsCase[]> {
  const res = await apiClient.get(`${base(projectId)}/cases`, { params });
  return res.data?.items ?? [];
}
export async function getCase(projectId: string, id: string): Promise<QmsCaseDetail> {
  const res = await apiClient.get(`${base(projectId)}/cases/${id}`);
  return res.data;
}
export async function createCase(projectId: string, body: {
  code: string; title: string; severity?: string; source_alert_id?: string | null; keywords?: string | null;
}): Promise<{ id: string; status: string }> {
  const res = await apiClient.post(`${base(projectId)}/cases`, body);
  return res.data;
}
export async function linkCaseObject(projectId: string, caseId: string, objectType: string, objectId: string): Promise<void> {
  await apiClient.post(`${base(projectId)}/cases/${caseId}/links`, { object_type: objectType, object_id: objectId });
}
export async function repushCase(projectId: string, caseId: string): Promise<{ status: string }> {
  const res = await apiClient.post(`${base(projectId)}/cases/${caseId}/repush`, {});
  return res.data;
}

// ---- 知识库（B3-10） ----
export async function listKnowledge(projectId: string, params?: {
  defect_code?: string; keyword?: string; device_ref?: string;
}): Promise<QmsKnowledgeEntry[]> {
  const res = await apiClient.get(`${base(projectId)}/knowledge`, { params });
  return res.data?.items ?? [];
}
export async function createKnowledge(projectId: string, body: {
  defect_code: string; symptom: string; root_cause?: string | null;
  action?: string | null; effectiveness?: string | null; device_ref?: string | null;
}): Promise<{ id: string }> {
  const res = await apiClient.post(`${base(projectId)}/knowledge`, body);
  return res.data;
}
export async function searchBySymptom(projectId: string, symptom: string): Promise<QmsSymptomHit[]> {
  const res = await apiClient.get(`${base(projectId)}/knowledge/symptom-search`, { params: { symptom } });
  return res.data?.items ?? [];
}

// ---- 追溯（B3-09） ----
export async function traceSample(projectId: string, sampleKey: string): Promise<QmsTraceResult> {
  const res = await apiClient.get(`${base(projectId)}/trace/${encodeURIComponent(sampleKey)}`);
  return res.data;
}
export async function traceBatch(projectId: string, batchNo: string): Promise<QmsTraceBatch> {
  const res = await apiClient.get(`${base(projectId)}/trace-batch/${encodeURIComponent(batchNo)}`);
  return res.data;
}

// ---- 质量报告（B3-08） ----
export async function listReports(projectId: string): Promise<QmsReport[]> {
  const res = await apiClient.get(`${base(projectId)}/quality-reports`);
  return res.data?.items ?? [];
}
export async function createReport(projectId: string, period: string, periodKey: string): Promise<{ id: string }> {
  const res = await apiClient.post(`${base(projectId)}/quality-reports`, { period, period_key: periodKey });
  return res.data;
}

// ---- 控制计划（B3-06） ----
export async function listControlPlans(projectId: string): Promise<QmsControlPlan[]> {
  const res = await apiClient.get(`${base(projectId)}/control-plans`);
  return res.data?.items ?? [];
}
export async function createControlPlan(projectId: string, body: {
  code: string; quality_points: { name: string; sample?: number }[];
}): Promise<{ id: string; version: number; status: string }> {
  const res = await apiClient.post(`${base(projectId)}/control-plans`, body);
  return res.data;
}
export async function planDiff(projectId: string, planId: string): Promise<QmsPlanDiff> {
  const res = await apiClient.get(`${base(projectId)}/control-plans/${planId}/diff`);
  return res.data;
}
export async function evaluateTightening(projectId: string, planId: string): Promise<{
  suggested_multiplier: number; factors: Record<string, { contribution: number }>;
}> {
  const res = await apiClient.post(`${base(projectId)}/control-plans/${planId}/tightening-evaluation`, {});
  return res.data;
}

// ---- MSA（B3-01） ----
export async function listMsaStudies(projectId: string): Promise<QmsMsaStudy[]> {
  const res = await apiClient.get(`${base(projectId)}/msa-studies`);
  return res.data?.items ?? [];
}
export async function createMsaStudy(projectId: string, body: {
  name: string; part_count: number; operator_count: number; replicates: number;
  tolerance: number; data: { readings: number[][][] };
}): Promise<{ id: string; grr_percent: number | null; ndc: number | null; grade: GrrGrade | null }> {
  const res = await apiClient.post(`${base(projectId)}/msa-studies`, body);
  return res.data;
}

// ---- FMEA（B3-02） ----
export async function listFmeas(projectId: string): Promise<QmsFmea[]> {
  const res = await apiClient.get(`${base(projectId)}/fmeas`);
  return res.data?.items ?? [];
}
export async function createFmea(projectId: string, body: {
  name: string; items: { failure_mode: string; effect?: string; severity: number; occurrence: number; detection: number; prevention?: string }[];
}): Promise<{ id: string; items: QmsFmeaItem[] }> {
  const res = await apiClient.post(`${base(projectId)}/fmeas`, body);
  return res.data;
}
export async function syncFmea(projectId: string, fmeaId: string, planId: string): Promise<{ approval_id: string; high_rpn_items: number }> {
  const res = await apiClient.post(
    `${base(projectId)}/fmeas/${fmeaId}/sync-control-plan?plan_id=${encodeURIComponent(planId)}`, {});
  return res.data;
}

// ---- IQC → SCAR（B3-05） ----
export async function listSuppliers(projectId: string): Promise<QmsSupplier[]> {
  const res = await apiClient.get(`${base(projectId)}/suppliers`);
  return res.data?.items ?? [];
}
export async function createSupplier(projectId: string, body: { code: string; name: string }): Promise<{ id: string; status: string }> {
  const res = await apiClient.post(`${base(projectId)}/suppliers`, body);
  return res.data;
}
export async function disableSupplier(projectId: string, id: string): Promise<{ status: string }> {
  const res = await apiClient.post(`${base(projectId)}/suppliers/${id}/disable`, {});
  return res.data;
}
export async function listIqcRecords(projectId: string): Promise<QmsIqcRecord[]> {
  const res = await apiClient.get(`${base(projectId)}/iqc-records`);
  return res.data?.items ?? [];
}
export async function createIqcRecord(projectId: string, body: {
  supplier_id: string; arrival_count: number; inspected_count: number; defect_count: number;
}): Promise<{ id: string; scar_id: string | null }> {
  const res = await apiClient.post(`${base(projectId)}/iqc-records`, body);
  return res.data;
}
export async function listScars(projectId: string): Promise<QmsScar[]> {
  const res = await apiClient.get(`${base(projectId)}/scars`);
  return res.data?.items ?? [];
}
