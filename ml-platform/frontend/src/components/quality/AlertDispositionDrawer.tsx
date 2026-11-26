import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert, App as AntApp, Button, Checkbox, Col, Descriptions, Drawer, Empty, Form, Input,
  List, Row, Select, Space, Steps, Tag, Timeline, Tooltip, Typography, Upload,
} from "antd";
import { UploadOutlined } from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import {
  ALERT_LABELS, SEVERITY_COLOR, STATUS_COLOR, alertEvidenceText,
  ackQualityAlert, apiErrorText, assignQualityAlert, disposeQualityAlert, getAlertCriteria,
  getAlertWaveform, getQualityAlert, requestAlertReview, transitionQualityAlert,
  uploadAlertAttachment,
} from "../../api/qualityAlerts";
import type {
  AlertResolution, AlertStatus, Criterion, QualityAlertDetail, WaveformResponse,
} from "../../api/qualityAlerts";
import { useI18n } from "../../i18n";
import { formatLocalTime } from "../../utils/time";

/** 处置工作台抽屉（B1-02）：预警中心与处置工作台共用。技术方案 §9.8。 */

const STATUS_ORDER: AlertStatus[] = ["open", "acknowledged", "processing", "review_pending", "closed"];

const CRITERIA_LABELS = {
  zh: { spec_exceed: "规格超限", sigma_3: "3σ 超限", sigma_2: "2σ 偏离", baseline_deviation_30: "基线偏离 30%" },
  en: { spec_exceed: "Spec limit", sigma_3: "3σ limit", sigma_2: "2σ deviation", baseline_deviation_30: "30% baseline deviation" },
};

const ACTION_LABELS = {
  zh: { to_processing: "开始处理", to_review_pending: "请求复核", back_to_processing: "退回处理" },
  en: { to_processing: "Start handling", to_review_pending: "Request review", back_to_processing: "Send back" },
};

function text(value: unknown): string {
  return value === null || value === undefined || value === "" ? "-" : String(value);
}

function shortId(value: unknown): string {
  const raw = text(value);
  return raw.length > 10 ? `${raw.slice(0, 8)}…` : raw;
}

function criterionDetailText(criterion: Criterion, zh: boolean): string {
  const detail = criterion.detail;
  if (typeof detail === "string") return detail;
  if (!detail || typeof detail !== "object") return "";
  const data = detail as Record<string, unknown>;
  const parts: string[] = [];
  if (data.usl != null || data.lsl != null) {
    parts.push(`${zh ? "限" : "limits"} ${text(data.lsl)} ~ ${text(data.usl)}${data.unit ? ` ${String(data.unit)}` : ""}`);
  }
  if (data.center != null && data.sigma != null) {
    parts.push(`${zh ? "中心" : "center"} ${text(data.center)} / σ ${text(data.sigma)}`);
  }
  if (data.deviation_ratio != null) parts.push(`${zh ? "偏离" : "deviation"} ${(Number(data.deviation_ratio) * 100).toFixed(1)}%`);
  return parts.join("；");
}

function waveformOption(points: number[], unit: string | undefined, spec: { target: number | null; usl: number | null; lsl: number | null } | undefined, zh: boolean) {
  const series: Record<string, unknown> = {
    type: "line", showSymbol: false, data: points,
    lineStyle: { width: 1.4 },
    areaStyle: { opacity: 0.08 },
  };
  if (spec) {
    const lines: Record<string, unknown>[] = [];
    if (spec.usl != null) lines.push({ yAxis: spec.usl, name: "USL", lineStyle: { color: "#cf1322", type: "dashed" } });
    if (spec.lsl != null) lines.push({ yAxis: spec.lsl, name: "LSL", lineStyle: { color: "#cf1322", type: "dashed" } });
    if (spec.target != null) lines.push({ yAxis: spec.target, name: zh ? "目标" : "Target", lineStyle: { color: "#1677ff", type: "dotted" } });
    if (lines.length) series.markLine = { silent: true, symbol: "none", label: { position: "insideEndTop" }, data: lines };
    if (spec.usl != null && spec.lsl != null) {
      series.markArea = {
        silent: true, itemStyle: { color: "rgba(22, 119, 255, 0.06)" },
        data: [[{ yAxis: spec.lsl }, { yAxis: spec.usl }]],
      };
    }
  }
  return {
    grid: { left: 48, right: 16, top: 28, bottom: 28 },
    xAxis: { type: "category", show: false, data: points.map((_, index) => String(index)) },
    yAxis: { type: "value", name: unit ?? "", axisLabel: { formatter: (value: number) => String(value) } },
    tooltip: { trigger: "axis", formatter: (params: { dataIndex: number; value: number }[]) => `#${params[0].dataIndex}: ${params[0].value}` },
    series: [series],
  };
}

export interface AlertDispositionDrawerProps {
  projectId: string;
  alertId: string | null;
  /** 可选责任人（项目成员 + 项目负责人） */
  assigneeOptions: { value: string; label: string }[];
  stationName: (stationId: string | null) => string;
  sceneName: (sceneId: string | null) => string;
  onClose: () => void;
  /** 预警状态变化后通知父级刷新列表 */
  onChanged: () => void;
}

interface FormValues {
  resolution: AlertResolution;
  type?: string;
  cause?: string;
  action?: string;
  downtime?: boolean;
  rework?: boolean;
  expanded_inspection?: boolean;
  note?: string;
}

export default function AlertDispositionDrawer({
  projectId, alertId, assigneeOptions, stationName, sceneName, onClose, onChanged,
}: AlertDispositionDrawerProps) {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [detail, setDetail] = useState<QualityAlertDetail | null>(null);
  const [criteria, setCriteria] = useState<Criterion[]>([]);
  const [waveform, setWaveform] = useState<WaveformResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [assignee, setAssignee] = useState<string | undefined>(undefined);
  const [form] = Form.useForm<FormValues>();

  const load = useCallback(() => {
    if (!alertId) { setDetail(null); setCriteria([]); setWaveform(null); return; }
    getQualityAlert(projectId, alertId).then((data) => {
      setDetail(data);
      setAssignee((current) => current ?? data.assigned_to ?? undefined);
    }).catch((e) => message.error(apiErrorText(e)));
    getAlertCriteria(projectId, alertId).then(setCriteria).catch(() => setCriteria([]));
    getAlertWaveform(projectId, alertId).then(setWaveform).catch(() => setWaveform(null));
  }, [projectId, alertId, message]);

  useEffect(() => { load(); }, [load]);

  const run = useCallback(async (operation: () => Promise<unknown>, successText: string) => {
    setBusy(true);
    try {
      await operation();
      message.success(successText);
      onChanged();
      load();
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  }, [load, message, onChanged]);

  const status = detail?.status ?? "open";
  const allowed = useMemo(() => new Set(detail?.allowed_transitions ?? []), [detail]);
  const isClosed = status === "closed";

  const submitDisposition = (values: FormValues) => {
    if (values.resolution === "confirmed_issue" && !(values.cause?.trim() && values.action?.trim())) {
      message.warning(zh ? "确认为真实异常时须填写原因与措施" : "Cause and action are required for a confirmed issue");
      return;
    }
    void run(() => disposeQualityAlert(projectId, alertId!, values), zh ? "处置已提交" : "Disposition submitted");
  };

  const latestDisposition = useMemo(() => {
    const events = detail?.events ?? [];
    for (let index = events.length - 1; index >= 0; index -= 1) {
      if (events[index].action === "disposition_submitted") return events[index];
    }
    return null;
  }, [detail]);

  const attachments = useMemo(
    () => (detail?.events ?? []).filter((event) => event.action === "attachment_added"),
    [detail],
  );

  const evidence = detail?.evidence ?? {};
  const specCriterion = criteria.find((item) => item.criterion === "spec_exceed");
  const sigmaCriterion = criteria.find((item) => item.criterion === "sigma_3");
  const specDetail = (specCriterion?.detail ?? null) as Record<string, unknown> | string | null;
  const sigmaDetail = (sigmaCriterion?.detail ?? null) as Record<string, unknown> | null;
  const chartSpec = waveform?.status === "ok" && waveform.specs.length ? waveform.specs[0] : undefined;

  const specLimitsText = (() => {
    if (specDetail && typeof specDetail === "object" && (specDetail.usl != null || specDetail.lsl != null)) {
      const unit = specDetail.unit ? ` ${String(specDetail.unit)}` : "";
      return `${text(specDetail.lsl)} ~ ${text(specDetail.usl)}${unit}`;
    }
    return zh ? "无规格定义" : "No spec defined";
  })();
  const baselineText = (() => {
    if (sigmaDetail && sigmaDetail.center != null) {
      const baseline = (sigmaDetail.baseline ?? {}) as Record<string, unknown>;
      return `${zh ? "中心" : "center"} ${text(sigmaDetail.center)} / σ ${text(sigmaDetail.sigma)}（v${text(baseline.version)}）`;
    }
    return sigmaCriterion?.status === "skipped"
      ? String(sigmaCriterion?.detail ?? (zh ? "未冻结基线" : "No frozen baseline"))
      : zh ? "未冻结基线" : "No frozen baseline";
  })();
  const modelBasisText = (() => {
    const kind = String(evidence.kind ?? detail?.source_type ?? "");
    if (kind === "model_risk") {
      const rule = String(evidence.rule ?? "threshold");
      const ruleText = rule.includes("is_anomaly") ? (zh ? "模型判异" : "model flagged") : (zh ? "越过触发下限" : "over trigger threshold");
      return `${ruleText} · ${zh ? "模型版本" : "model"} ${shortId(evidence.model_version_id)}`;
    }
    if (kind === "param_exceed") return zh ? "规格定义（场景配置，单一来源）" : "Spec definition (scene config)";
    if (kind === "device_anomaly") return `${zh ? "最近心跳" : "Last heartbeat"} ${evidence.last_heartbeat ? formatLocalTime(String(evidence.last_heartbeat)) : (zh ? "从未" : "never")}`;
    return "-";
  })();

  const dispositionForm = latestDisposition?.form_snapshot ?? null;

  return (
    <Drawer
      open={Boolean(alertId)}
      onClose={onClose}
      width={920}
      destroyOnClose
      title={detail ? (
        <Space wrap data-testid="alert-drawer-title">
          <Typography.Text strong>{detail.title}</Typography.Text>
          <Tag color={SEVERITY_COLOR[detail.severity]}>{ALERT_LABELS.severity[lang][detail.severity]}</Tag>
          <Tag>{ALERT_LABELS.source[lang][detail.source_type]}</Tag>
          <Tag color={STATUS_COLOR[detail.status]}>{ALERT_LABELS.status[lang][detail.status]}</Tag>
          {detail.is_demo && <Tag color="magenta">{zh ? "演示" : "Demo"}</Tag>}
          {detail.occurrence_count > 1 && (
            <Tag color="blue">{zh ? `同因 ×${detail.occurrence_count}` : `Merged ×${detail.occurrence_count}`}</Tag>
          )}
        </Space>
      ) : null}
    >
      {!detail ? <Empty description={zh ? "加载中…" : "Loading…"} /> : (
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Steps
            size="small"
            current={STATUS_ORDER.indexOf(status)}
            status={isClosed ? "finish" : "process"}
            items={STATUS_ORDER.map((key) => ({ title: ALERT_LABELS.status[lang][key] }))}
          />

          <Descriptions
            size="small" bordered column={{ xs: 1, md: 2 }}
            title={zh ? "证据区" : "Evidence"}
            data-testid="alert-evidence"
          >
            <Descriptions.Item label={zh ? "实测值" : "Measured"}>{alertEvidenceText(detail, zh)}</Descriptions.Item>
            <Descriptions.Item label={zh ? "规格上下限" : "Spec limits"}>{specLimitsText}</Descriptions.Item>
            <Descriptions.Item label={zh ? "基线（冻结版本）" : "Baseline (frozen)"}>{baselineText}</Descriptions.Item>
            <Descriptions.Item label={zh ? "模型依据" : "Model basis"}>{modelBasisText}</Descriptions.Item>
            <Descriptions.Item label={zh ? "样本键 / 批次" : "Sample / batch"}>
              {text(detail.sample_key)} / {text(detail.batch_no)}
            </Descriptions.Item>
            <Descriptions.Item label={zh ? "场景 / 工位" : "Scene / station"}>
              {sceneName(detail.scene_id)} / {stationName(detail.station_id)}
            </Descriptions.Item>
          </Descriptions>

          <section data-testid="alert-criteria">
            <Typography.Title level={5}>{zh ? "判据链（按当前规格与冻结基线复算）" : "Criteria chain (recomputed)"}</Typography.Title>
            <List
              size="small"
              dataSource={criteria}
              locale={{ emptyText: zh ? "无判据数据" : "No criteria" }}
              renderItem={(criterion) => (
                <List.Item>
                  <Space wrap>
                    <Tag color={criterion.status === "hit" ? "red" : criterion.status === "pass" ? "green" : "default"}>
                      {criterion.status === "hit" ? (zh ? "命中" : "Hit") : criterion.status === "pass" ? (zh ? "通过" : "Pass") : (zh ? "不适用" : "N/A")}
                    </Tag>
                    <Typography.Text>{(CRITERIA_LABELS[lang] as Record<string, string>)[criterion.criterion] ?? criterion.criterion}</Typography.Text>
                    <Typography.Text type="secondary">{criterionDetailText(criterion, zh)}</Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
          </section>

          <section data-testid="alert-waveform">
            <Typography.Title level={5}>{zh ? "曲线叠加" : "Waveform overlay"}</Typography.Title>
            {waveform?.status === "ok" ? (
              <ReactECharts
                notMerge
                style={{ height: 260 }}
                option={waveformOption(waveform.points, chartSpec?.unit ?? undefined, chartSpec, zh)}
              />
            ) : (
              /* 诚实设计③：说明为什么没有，以及第一步该做什么 */
              <Empty description={
                zh
                  ? `暂无波形：${waveform?.reason ?? "该预警没有可定位的波形样本"}。曲线来自场景波形列所在的就绪数据集版本；请确认场景已声明波形字段角色且样本键一致。`
                  : `No waveform: ${waveform?.reason ?? "no locatable waveform sample"}. Declare the scene waveform role and keep sample keys consistent.`
              } />
            )}
          </section>

          {!isClosed && (
            <section data-testid="alert-actions">
              <Typography.Title level={5}>{zh ? "处置动作" : "Actions"}</Typography.Title>
              <Space wrap>
                <Select
                  aria-label={zh ? "责任人" : "Assignee"}
                  showSearch
                  optionFilterProp="label"
                  style={{ minWidth: 200 }}
                  placeholder={zh ? "选择责任人（必填）" : "Assignee (required)"}
                  value={assignee}
                  onChange={(value: string) => setAssignee(value)}
                  options={assigneeOptions}
                />
                {status === "open" && (
                  <Button
                    type="primary"
                    data-testid="alert-ack"
                    disabled={!assignee}
                    loading={busy}
                    onClick={() => run(() => ackQualityAlert(projectId, alertId!, assignee!), zh ? "已确认" : "Acknowledged")}
                  >
                    {zh ? "确认" : "Acknowledge"}
                  </Button>
                )}
                {status !== "open" && (
                  <Button
                    data-testid="alert-transfer"
                    disabled={!assignee || assignee === detail.assigned_to}
                    loading={busy}
                    onClick={() => run(() => assignQualityAlert(projectId, alertId!, assignee!), zh ? "已转交" : "Transferred")}
                  >
                    {zh ? "转交" : "Transfer"}
                  </Button>
                )}
                {status === "acknowledged" && allowed.has("processing") && (
                  <Button data-testid="alert-start" loading={busy} onClick={() => run(() => transitionQualityAlert(projectId, alertId!, "processing"), ACTION_LABELS[lang].to_processing)}>
                    {ACTION_LABELS[lang].to_processing}
                  </Button>
                )}
                {allowed.has("review_pending") && (
                  <Button data-testid="alert-review" loading={busy} onClick={() => run(() => requestAlertReview(projectId, alertId!), ACTION_LABELS[lang].to_review_pending)}>
                    {ACTION_LABELS[lang].to_review_pending}
                  </Button>
                )}
                {status === "review_pending" && allowed.has("processing") && (
                  <Button data-testid="alert-send-back" loading={busy} onClick={() => run(() => transitionQualityAlert(projectId, alertId!, "processing"), ACTION_LABELS[lang].back_to_processing)}>
                    {ACTION_LABELS[lang].back_to_processing}
                  </Button>
                )}
                <Tooltip title={zh ? "NCR/CAPA 随第三批质量体系接入，接口已预留" : "NCR/CAPA arrives with the batch-3 quality system; interface reserved"}>
                  <Button disabled>{zh ? "登记 NCR" : "Register NCR"}</Button>
                </Tooltip>
              </Space>
              {status === "open" && (
                <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                  {zh ? "确认前必须指定责任人——责任人为空时无法确认（避免预警无人认领）。" : "An assignee is required before acknowledging."}
                </Typography.Paragraph>
              )}
            </section>
          )}

          {!isClosed && allowed.has("closed") && (
            <Form
              form={form} layout="vertical" data-testid="disposition-form"
              initialValues={{ resolution: "confirmed_issue", downtime: false, rework: false, expanded_inspection: false }}
              onFinish={submitDisposition}
            >
              <Typography.Title level={5}>{zh ? "处置表单" : "Disposition"}</Typography.Title>
              <Form.Item name="resolution" label={zh ? "关闭结论" : "Resolution"} rules={[{ required: true }]}>
                <Select
                  options={(Object.keys(ALERT_LABELS.resolution[lang]) as AlertResolution[]).map((key) => ({
                    value: key, label: ALERT_LABELS.resolution[lang][key],
                  }))}
                />
              </Form.Item>
              <Form.Item name="type" label={zh ? "处置类型" : "Type"}>
                <Select
                  allowClear
                  options={(zh
                    ? ["参数调整", "设备维修", "工艺变更", "来料问题", "人工复判", "其他"]
                    : ["Parameter adjustment", "Device repair", "Process change", "Incoming material", "Manual review", "Other"]
                  ).map((label) => ({ value: label, label }))}
                />
              </Form.Item>
              <Form.Item name="cause" label={zh ? "原因" : "Cause"}>
                <Input.TextArea rows={2} placeholder={zh ? "确认异常时必填" : "Required for a confirmed issue"} />
              </Form.Item>
              <Form.Item name="action" label={zh ? "措施" : "Action"}>
                <Input.TextArea rows={2} placeholder={zh ? "确认异常时必填" : "Required for a confirmed issue"} />
              </Form.Item>
              <Row gutter={16}>
                <Col span={8}><Form.Item name="downtime" valuePropName="checked"><Checkbox>{zh ? "停机" : "Downtime"}</Checkbox></Form.Item></Col>
                <Col span={8}><Form.Item name="rework" valuePropName="checked"><Checkbox>{zh ? "返工" : "Rework"}</Checkbox></Form.Item></Col>
                <Col span={8}><Form.Item name="expanded_inspection" valuePropName="checked"><Checkbox>{zh ? "扩大检查" : "Expanded inspection"}</Checkbox></Form.Item></Col>
              </Row>
              <Form.Item name="note" label={zh ? "备注" : "Note"}><Input /></Form.Item>
              <Button type="primary" htmlType="submit" data-testid="disposition-submit" loading={busy}>
                {zh ? "提交处置并关闭" : "Submit and close"}
              </Button>
              <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
                {zh
                  ? "提交时会记录当时生效的 SOP 版本、SPC 基线版本与模型版本，后续变更不改写本单；误报结论会生成复核任务进入标注回流队列。"
                  : "The effective SOP, SPC baseline and model versions are frozen into this record; a false-positive outcome creates a review task."}
              </Typography.Paragraph>
            </Form>
          )}

          {isClosed && (
            <section data-testid="disposition-summary">
              <Typography.Title level={5}>
                {zh ? `处置结论：${detail.resolution ? ALERT_LABELS.resolution[lang][detail.resolution] : "-"}` : `Resolution: ${detail.resolution ? ALERT_LABELS.resolution[lang][detail.resolution] : "-"}`}
              </Typography.Title>
              {dispositionForm ? (
                <Descriptions size="small" column={1}>
                  <Descriptions.Item label={zh ? "类型" : "Type"}>{text(dispositionForm.type)}</Descriptions.Item>
                  <Descriptions.Item label={zh ? "原因" : "Cause"}>{text(dispositionForm.cause)}</Descriptions.Item>
                  <Descriptions.Item label={zh ? "措施" : "Action"}>{text(dispositionForm.action)}</Descriptions.Item>
                  <Descriptions.Item label={zh ? "标记" : "Flags"}>
                    {[dispositionForm.downtime && (zh ? "停机" : "Downtime"), dispositionForm.rework && (zh ? "返工" : "Rework"), dispositionForm.expanded_inspection && (zh ? "扩大检查" : "Expanded inspection")].filter(Boolean).join("、") || "-"}
                  </Descriptions.Item>
                </Descriptions>
              ) : null}
              {detail.outcome?.review_task_id && (
                <Alert type="info" style={{ marginTop: 8 }} message={zh ? `已生成误报复核任务 ${shortId(detail.outcome.review_task_id)}，可在数据标注页指派。` : `Review task ${shortId(detail.outcome.review_task_id)} created.`} />
              )}
            </section>
          )}

          <section data-testid="alert-attachments">
            <Space>
              <Typography.Title level={5} style={{ margin: 0 }}>{zh ? "附件" : "Attachments"}</Typography.Title>
              <Upload
                showUploadList={false}
                beforeUpload={(file) => {
                  void run(async () => { await uploadAlertAttachment(projectId, alertId!, file as File); }, zh ? "附件已上传" : "Attachment uploaded");
                  return false;
                }}
              >
                <Button icon={<UploadOutlined />} disabled={isClosed || !alertId}>{zh ? "上传附件" : "Upload"}</Button>
              </Upload>
            </Space>
            <List
              size="small"
              dataSource={attachments}
              locale={{ emptyText: zh ? "暂无附件" : "No attachments" }}
              renderItem={(event) => (
                <List.Item>
                  {String(event.form_snapshot?.name ?? "attachment")}
                  <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                    {Number(event.form_snapshot?.size ?? 0) > 0 ? `${Math.ceil(Number(event.form_snapshot?.size) / 1024)} KB` : ""} · {formatLocalTime(event.created_at)}
                  </Typography.Text>
                </List.Item>
              )}
            />
          </section>

          <section data-testid="alert-trail">
            <Typography.Title level={5}>{zh ? "处置轨迹" : "Trail"}</Typography.Title>
            <Timeline
              mode="left"
              items={(detail.events ?? []).slice().reverse().map((event) => ({
                children: (
                  <div>
                    <Typography.Text strong>{ALERT_LABELS.action[lang][event.action] ?? event.action}</Typography.Text>
                    {event.from_status && event.to_status && (
                      <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                        {ALERT_LABELS.status[lang][event.from_status as AlertStatus] ?? event.from_status} → {ALERT_LABELS.status[lang][event.to_status as AlertStatus] ?? event.to_status}
                      </Typography.Text>
                    )}
                    <div>
                      <Typography.Text type="secondary">
                        {formatLocalTime(event.created_at)} · {shortId(event.actor)}
                      </Typography.Text>
                      {event.note ? ` · ${event.note}` : ""}
                    </div>
                  </div>
                ),
              }))}
            />
          </section>
        </Space>
      )}
    </Drawer>
  );
}
