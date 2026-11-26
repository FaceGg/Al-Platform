import apiClient from "./client";

/** 质量预警与处置 API（补齐路线第一批 F2a，B1-01/B1-02，技术方案 §9.7）。 */

export type AlertSourceType =
  | "model_risk" | "param_exceed" | "device_anomaly"
  | "spc_violation" | "sensor_anomaly" | "curve_deviation";
export type AlertSeverity = "warning" | "high" | "critical";
export type AlertStatus = "open" | "acknowledged" | "processing" | "review_pending" | "closed";
export type AlertResolution = "false_positive" | "confirmed_issue" | "other";

export interface QualityAlert {
  id: string;
  project_id: string;
  scene_id: string | null;
  station_id: string | null;
  device_id: string | null;
  condition_value: string | null;
  source_type: AlertSourceType;
  risk_score: number | null;
  severity: AlertSeverity;
  title: string;
  sample_key: string | null;
  batch_no: string | null;
  product_code: string | null;
  evidence: Record<string, unknown>;
  status: AlertStatus;
  assigned_to: string | null;
  first_ack_at: string | null;
  closed_at: string | null;
  sla_due_at: string | null;
  sla_notify_level: number;
  resolution: AlertResolution | null;
  occurrence_count: number;
  merge_key: string;
  merge_open: boolean;
  last_event_at: string | null;
  is_demo: boolean;
  created_at: string | null;
}

export interface QualityAlertEvent {
  id: string;
  alert_id: string;
  action: string;
  from_status: string | null;
  to_status: string | null;
  actor: string | null;
  note: string | null;
  form_snapshot: Record<string, unknown> | null;
  snapshot: Record<string, unknown> | null;
  created_at: string | null;
}

export interface DispositionOutcome {
  bucket_confirmed: boolean;
  review_task_id: string | null;
}

export interface QualityAlertDetail extends QualityAlert {
  events: QualityAlertEvent[];
  allowed_transitions: AlertStatus[];
  outcome?: DispositionOutcome;
}

export interface AlertPage {
  items: QualityAlert[];
  total: number;
  page: number;
  page_size: number;
}

export type CriterionStatus = "hit" | "pass" | "skipped";
export interface Criterion {
  criterion: string;
  status: CriterionStatus;
  detail: unknown;
}

export interface WaveformSpec {
  statistic: string;
  target: number | null;
  usl: number | null;
  lsl: number | null;
  unit: string | null;
}

export type WaveformResponse =
  | { status: "ok"; column: string; points: number[]; dataset_version_id: string; specs: WaveformSpec[] }
  | { status: "no_waveform" | "decode_failed"; reason: string };

export interface QualitySop {
  id: string;
  project_id: string;
  scene_id: string | null;
  code: string;
  version: number;
  title: string;
  content: { spec_exceed?: string[]; spc_exceed?: string[]; ai_risk?: string[] };
  condition_value: string | null;
  effective_from: string | null;
  retired_at: string | null;
  is_active: boolean;
}

export interface QualitySpcBaseline {
  id: string;
  field: string;
  statistic: string;
  station_id: string | null;
  condition_value: string | null;
  center: number;
  sigma: number;
  sample_count: number;
  version: number;
  is_active: boolean;
  window_start: string | null;
  window_end: string | null;
}

/** 预警规则（D14）：触发下限独立于分级阈值。未配置的键由平台默认兜底。 */
export interface AlertSettings {
  trigger_threshold?: number;
  high_threshold?: number;
  critical_threshold?: number;
  sla_hours?: number;
  merge_window_minutes?: number;
}
export type ResolvedAlertSettings = Required<AlertSettings>;

export interface AlertListParams {
  status?: string;
  severity?: string;
  source_type?: string;
  scene_id?: string;
  station_id?: string;
  sample_key?: string;
  batch_no?: string;
  include_demo?: boolean;
  sla_overdue?: boolean;
  /** 未关闭（待确认 / 已确认 / 处理中 / 待复核）——与驾驶舱「待处理」卡同口径 */
  open?: boolean;
  /** 不低于某级别（warning / high / critical）——与驾驶舱「高风险」卡同口径 */
  min_severity?: string;
  occurred_from?: string;
  occurred_to?: string;
  page?: number;
  page_size?: number;
}

function withParams(params: AlertListParams) {
  const query: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "" || value === null) continue;
    query[key] = typeof value === "boolean" ? String(value) : value;
  }
  return { params: query };
}

function pageOf(data: unknown): AlertPage {
  const body = (data ?? {}) as Partial<AlertPage>;
  return {
    items: Array.isArray(body.items) ? body.items : [],
    total: Number(body.total || 0),
    page: Number(body.page || 1),
    page_size: Number(body.page_size || 20),
  };
}

/** 从请求错误里取出可读说明：优先接口的 {detail: {message, code}}，否则错误文本。 */
export function apiErrorText(e: unknown): string {
  const body = (e as { response?: { data?: { detail?: { message?: string; code?: string } } } } | null)
    ?.response?.data?.detail;
  return body?.message || body?.code || String(e);
}

export async function listQualityAlerts(projectId: string, params: AlertListParams = {}): Promise<AlertPage> {
  const res = await apiClient.get(`/projects/${projectId}/quality-alerts`, withParams(params));
  return pageOf(res.data);
}

export async function getQualityAlert(projectId: string, alertId: string): Promise<QualityAlertDetail> {
  const res = await apiClient.get(`/projects/${projectId}/quality-alerts/${alertId}`);
  return res.data;
}

async function postAction(projectId: string, alertId: string, action: string, body: unknown = {}) {
  const res = await apiClient.post(`/projects/${projectId}/quality-alerts/${alertId}/${action}`, body);
  return res.data as QualityAlertDetail;
}

export const ackQualityAlert = (projectId: string, alertId: string, assigneeId: string, note?: string) =>
  postAction(projectId, alertId, "ack", { assignee_id: assigneeId, note });
export const assignQualityAlert = (projectId: string, alertId: string, assigneeId: string, note?: string) =>
  postAction(projectId, alertId, "assign", { assignee_id: assigneeId, note });
export const transferQualityAlert = (projectId: string, alertId: string, assigneeId: string, note?: string) =>
  postAction(projectId, alertId, "transfer", { assignee_id: assigneeId, note });
export const transitionQualityAlert = (
  projectId: string, alertId: string, toStatus: AlertStatus, extra: { note?: string; resolution?: AlertResolution } = {},
) => postAction(projectId, alertId, "transition", { to_status: toStatus, ...extra });
export const requestAlertReview = (projectId: string, alertId: string) =>
  postAction(projectId, alertId, "request-review");

export interface DispositionForm {
  resolution: AlertResolution;
  type?: string;
  cause?: string;
  action?: string;
  downtime?: boolean;
  rework?: boolean;
  expanded_inspection?: boolean;
  note?: string;
}

export async function disposeQualityAlert(
  projectId: string, alertId: string, form: DispositionForm,
): Promise<DispositionOutcome> {
  const res = await apiClient.post(`/projects/${projectId}/quality-alerts/${alertId}/disposition`, form);
  return (res.data?.outcome ?? { bucket_confirmed: false, review_task_id: null }) as DispositionOutcome;
}

export async function getAlertCriteria(projectId: string, alertId: string): Promise<Criterion[]> {
  const res = await apiClient.get(`/projects/${projectId}/quality-alerts/${alertId}/criteria`);
  return Array.isArray(res.data?.criteria) ? res.data.criteria : [];
}

export async function getAlertWaveform(projectId: string, alertId: string): Promise<WaveformResponse> {
  const res = await apiClient.get(`/projects/${projectId}/quality-alerts/${alertId}/waveform`);
  return res.data;
}

/** CSV 导出走带鉴权的请求再落盘（不用裸链接——那会丢掉令牌）。返回文件名与对象地址。 */
export async function exportAlertsCsv(projectId: string, params: AlertListParams = {}) {
  const res = await apiClient.get(`/projects/${projectId}/quality-alerts/export.csv`, {
    ...withParams(params),
    responseType: "blob",
  });
  return res.data as Blob;
}

export async function uploadAlertAttachment(projectId: string, alertId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  const res = await apiClient.post(`/projects/${projectId}/quality-alerts/${alertId}/attachments`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data as { artifact_id: string; name: string; size: number };
}

export async function listQualitySops(projectId: string, activeOnly = false): Promise<QualitySop[]> {
  const res = await apiClient.get(`/projects/${projectId}/quality-sops`, { params: { active_only: String(activeOnly) } });
  return res.data?.items ?? [];
}

export async function createQualitySop(projectId: string, body: {
  code: string; title: string; content: QualitySop["content"]; scene_id?: string | null; condition_value?: string | null;
}): Promise<QualitySop> {
  const res = await apiClient.post(`/projects/${projectId}/quality-sops`, body);
  return res.data;
}

export async function getAlertSettings(projectId: string, sceneId: string): Promise<{
  alert_settings: AlertSettings; resolved: ResolvedAlertSettings;
}> {
  const res = await apiClient.get(`/projects/${projectId}/quality-scenes/${sceneId}/alert-settings`);
  return res.data;
}

export async function updateAlertSettings(projectId: string, sceneId: string, settings: AlertSettings): Promise<{
  alert_settings: AlertSettings; resolved: ResolvedAlertSettings;
}> {
  const res = await apiClient.put(`/projects/${projectId}/quality-scenes/${sceneId}/alert-settings`, settings);
  return res.data;
}

export async function listSpcBaselines(projectId: string, sceneId: string): Promise<QualitySpcBaseline[]> {
  const res = await apiClient.get(`/projects/${projectId}/quality-scenes/${sceneId}/spc-baselines`);
  return res.data?.items ?? [];
}

export async function freezeSpcBaseline(projectId: string, sceneId: string, body: {
  dataset_version_id: string; field: string; statistic?: string; station_id?: string | null;
  condition_value?: string | null; row_index_from?: number; row_index_to?: number;
  time_from?: string; time_to?: string;
}): Promise<QualitySpcBaseline> {
  const res = await apiClient.post(`/projects/${projectId}/quality-scenes/${sceneId}/spc-baselines`, body);
  return res.data;
}

/** 文案表（中文 / 英文）。来源六类里后三类随 F4 接入，文案先行占位以免出现裸枚举值。 */
export const ALERT_LABELS = {
  source: {
    zh: { model_risk: "模型风险", param_exceed: "参数超限", device_anomaly: "设备异常", spc_violation: "SPC 判异", sensor_anomaly: "传感器异常", curve_deviation: "曲线偏离" } as Record<AlertSourceType, string>,
    en: { model_risk: "Model risk", param_exceed: "Parameter limit", device_anomaly: "Device anomaly", spc_violation: "SPC rule", sensor_anomaly: "Sensor anomaly", curve_deviation: "Curve deviation" } as Record<AlertSourceType, string>,
  },
  severity: {
    zh: { warning: "关注", high: "高风险", critical: "严重" } as Record<AlertSeverity, string>,
    en: { warning: "Warning", high: "High", critical: "Critical" } as Record<AlertSeverity, string>,
  },
  status: {
    zh: { open: "待确认", acknowledged: "已确认", processing: "处理中", review_pending: "待复核", closed: "已关闭" } as Record<AlertStatus, string>,
    en: { open: "Open", acknowledged: "Acknowledged", processing: "Processing", review_pending: "Review pending", closed: "Closed" } as Record<AlertStatus, string>,
  },
  resolution: {
    zh: { false_positive: "误报", confirmed_issue: "确认异常", other: "其他" } as Record<AlertResolution, string>,
    en: { false_positive: "False positive", confirmed_issue: "Confirmed issue", other: "Other" } as Record<AlertResolution, string>,
  },
  action: {
    zh: {
      created: "产生预警", occurred: "同因再次发生", acknowledged: "确认", assigned: "指定责任人",
      status_changed: "阶段流转", disposition_submitted: "提交处置", transfer: "转交",
      review_requested: "请求复核", attachment_added: "添加附件", comment: "备注",
      device_recovered: "设备恢复", sla_notified: "SLA 通知", review_task_created: "创建复核任务",
    } as Record<string, string>,
    en: {
      created: "Alert raised", occurred: "Recurred (merged)", acknowledged: "Acknowledged", assigned: "Assigned",
      status_changed: "Status changed", disposition_submitted: "Disposition submitted", transfer: "Transferred",
      review_requested: "Review requested", attachment_added: "Attachment added", comment: "Note",
      device_recovered: "Device recovered", sla_notified: "SLA notice", review_task_created: "Review task created",
    } as Record<string, string>,
  },
};

export const SEVERITY_COLOR: Record<AlertSeverity, string> = { warning: "gold", high: "orange", critical: "red" };
export const STATUS_COLOR: Record<AlertStatus, string> = {
  open: "error", acknowledged: "volcano", processing: "processing", review_pending: "purple", closed: "default",
};

/** 预警来源里可读的证据摘要（实测值 / 分数 / 设备名），证据区与列表共用。 */
export function alertEvidenceText(alert: Pick<QualityAlert, "evidence" | "source_type" | "risk_score">, zh: boolean): string {
  const evidence = alert.evidence || {};
  const kind = String(evidence.kind ?? alert.source_type);
  if (kind === "param_exceed") {
    const spec = (evidence.spec ?? {}) as { usl?: number | null; lsl?: number | null; unit?: string | null };
    const limits = [spec.lsl != null ? `LSL ${spec.lsl}` : null, spec.usl != null ? `USL ${spec.usl}` : null].filter(Boolean).join(" / ");
    return `${String(evidence.field ?? "")} = ${String(evidence.recorded_value ?? "-")}${spec.unit ?? ""}${limits ? `（${limits}）` : ""}`;
  }
  if (kind === "model_risk") {
    const scoreKind = evidence.score_kind === "anomaly_score" ? (zh ? "异常分数" : "anomaly score") : (zh ? "预测概率" : "probability");
    return `${scoreKind} ${String(evidence.score ?? "-")}（${zh ? "触发下限" : "trigger"} ${String(evidence.trigger_threshold ?? "-")}）`;
  }
  if (kind === "device_anomaly") return String(evidence.device_name ?? (zh ? "设备离线" : "Device offline"));
  return alert.risk_score != null ? String(alert.risk_score) : "-";
}

/** SLA 展示：返回 { text, overdue }。无到期时间或已关闭时不显示倒计时。 */
export function slaState(alert: Pick<QualityAlert, "sla_due_at" | "status">, now = Date.now()): { text: string; overdue: boolean } | null {
  if (!alert.sla_due_at || alert.status === "closed") return null;
  const due = Date.parse(alert.sla_due_at.endsWith("Z") ? alert.sla_due_at : `${alert.sla_due_at}Z`);
  if (Number.isNaN(due)) return null;
  const remaining = due - now;
  if (remaining <= 0) return { text: `-${Math.floor(-remaining / 60000)}m`, overdue: true };
  const hours = Math.floor(remaining / 3600000);
  const minutes = Math.floor((remaining % 3600000) / 60000);
  return { text: `${hours}h ${minutes}m`, overdue: false };
}
