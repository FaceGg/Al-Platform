import { useCallback, useEffect, useMemo, useState, type Key } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  App as AntApp, Button, Card, Col, Empty, Input, List, Modal, Row, Select, Space, Statistic, Switch,
  Table, Tag, Typography,
} from "antd";
import { DownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import {
  ALERT_LABELS, SEVERITY_COLOR, STATUS_COLOR, alertEvidenceText, ackQualityAlert,
  apiErrorText, exportAlertsCsv, getQualityAlert, listQualityAlerts, slaState,
} from "../api/qualityAlerts";
import type { AlertListParams, QualityAlert, QualityAlertEvent } from "../api/qualityAlerts";
import { useI18n } from "../i18n";
import { formatLocalTime } from "../utils/time";

/** 质量管理 · 监控 / 预警中心（B1-01，技术方案 §9.8）。 */

interface Filters {
  status?: string;
  severity?: string;
  source_type?: string;
  scene_id?: string;
  station_id?: string;
  sample_key?: string;
  include_demo?: boolean;
  /** 来自驾驶舱下钻：未关闭（四个阶段） / 不低于某级别 */
  open?: boolean;
  min_severity?: string;
}

/** 驾驶舱 KPI 卡下钻时把口径带在地址参数里，列表条数才与卡片数字一致。 */
function filtersFromLocation(searchParams: URLSearchParams): Filters {
  const seeded: Filters = {};
  for (const key of ["status", "severity", "min_severity", "station_id", "scene_id"] as const) {
    const value = searchParams.get(key);
    if (value) seeded[key] = value;
  }
  if (searchParams.get("open") === "1") seeded.open = true;
  return seeded;
}

const EMPTY_SUMMARY = { open: 0, handling: 0, review: 0, overdue: 0, today: 0 };

export default function QualityAlertsPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { projects, projectId, setProjectId, scenes, people, sceneName, stationName, userName } =
    useQualityAlertLookups();
  const [rows, setRows] = useState<QualityAlert[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState<Filters>(() => filtersFromLocation(searchParams));
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [selected, setSelected] = useState<Key[]>([]);
  const [batchTargets, setBatchTargets] = useState<QualityAlert[] | null>(null);
  const [assignee, setAssignee] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [occurrences, setOccurrences] = useState<Record<string, QualityAlertEvent[]>>({});

  const filterParams = useMemo<AlertListParams>(() => ({ ...filters }), [filters]);

  const load = useCallback(() => {
    if (!projectId) { setRows([]); setTotal(0); return; }
    setLoading(true);
    listQualityAlerts(projectId, { ...filterParams, page, page_size: pageSize })
      .then((result) => { setRows(result.items); setTotal(result.total); })
      .catch((e) => message.error(apiErrorText(e)))
      .finally(() => setLoading(false));
  }, [projectId, filterParams, page, pageSize, message]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!projectId) { setSummary(EMPTY_SUMMARY); return; }
    const base: AlertListParams = { page_size: 1, include_demo: Boolean(filters.include_demo) };
    const count = async (extra: AlertListParams) => {
      try { return (await listQualityAlerts(projectId, { ...base, ...extra })).total; } catch { return 0; }
    };
    const startOfToday = new Date(new Date().setHours(0, 0, 0, 0)).toISOString();
    void Promise.all([
      count({ status: "open" }),
      count({ status: "acknowledged" }),
      count({ status: "processing" }),
      count({ status: "review_pending" }),
      count({ sla_overdue: true }),
      count({ occurred_from: startOfToday }),
    ]).then(([open, acknowledged, processing, review, overdue, today]) => {
      setSummary({ open, handling: acknowledged + processing, review, overdue, today });
    });
  }, [projectId, filters.include_demo, total, load]);

  const openDisposition = (alertId: string) => navigate(`/quality/disposition?alert=${alertId}`);

  const confirmMany = async (targets: QualityAlert[]) => {
    if (!assignee || !projectId) return;
    setBusy(true);
    const results = await Promise.allSettled(
      targets.map((alert) => ackQualityAlert(projectId, alert.id, assignee)),
    );
    const failed = results.filter((result) => result.status === "rejected").length;
    if (failed === 0) message.success(zh ? `已确认 ${targets.length} 条预警` : `${targets.length} alerts acknowledged`);
    else message.warning(zh ? `${targets.length - failed} 条已确认，${failed} 条失败` : `${targets.length - failed} acknowledged, ${failed} failed`);
    setBusy(false);
    setBatchTargets(null);
    setAssignee(undefined);
    setSelected([]);
    load();
  };

  const exportCsv = async () => {
    if (!projectId) return;
    try {
      const blob = await exportAlertsCsv(projectId, filterParams);
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = "quality-alerts.csv";
      link.click();
      URL.revokeObjectURL(href);
    } catch (e) {
      message.error(apiErrorText(e));
    }
  };

  const loadOccurrences = async (alert: QualityAlert) => {
    if (occurrences[alert.id]) return;
    try {
      const detail = await getQualityAlert(projectId!, alert.id);
      setOccurrences((current) => ({
        ...current,
        [alert.id]: detail.events.filter((event) => event.action === "occurred"),
      }));
    } catch { /* 展开失败不阻断列表 */ }
  };

  const columns = [
    {
      title: zh ? "时间" : "Time", dataIndex: "created_at", key: "created_at", width: 170,
      render: (value: string | null) => (value ? formatLocalTime(value) : "-"),
    },
    {
      title: zh ? "级别" : "Severity", dataIndex: "severity", key: "severity", width: 90,
      render: (value: QualityAlert["severity"]) => <Tag color={SEVERITY_COLOR[value]}>{ALERT_LABELS.severity[lang][value]}</Tag>,
    },
    {
      title: zh ? "来源" : "Source", dataIndex: "source_type", key: "source_type", width: 110,
      render: (value: QualityAlert["source_type"]) => <Tag>{ALERT_LABELS.source[lang][value] ?? value}</Tag>,
    },
    {
      title: zh ? "预警" : "Alert", key: "title",
      render: (_: unknown, row: QualityAlert) => (
        <Space direction="vertical" size={0}>
          <Space wrap>
            <span>{row.title}</span>
            {row.is_demo && <Tag color="magenta">{zh ? "演示" : "Demo"}</Tag>}
            {row.occurrence_count > 1 && <Tag color="blue">{zh ? `同因 ×${row.occurrence_count}` : `Merged ×${row.occurrence_count}`}</Tag>}
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{alertEvidenceText(row, zh)}</Typography.Text>
        </Space>
      ),
    },
    {
      title: zh ? "场景 / 工位" : "Scene / station", key: "scope", width: 200,
      render: (_: unknown, row: QualityAlert) => `${sceneName(row.scene_id)} / ${stationName(row.station_id)}`,
    },
    {
      title: zh ? "状态" : "Status", dataIndex: "status", key: "status", width: 100,
      render: (value: QualityAlert["status"]) => <Tag color={STATUS_COLOR[value]}>{ALERT_LABELS.status[lang][value]}</Tag>,
    },
    {
      title: zh ? "责任人" : "Assignee", dataIndex: "assigned_to", key: "assigned_to", width: 110,
      render: (value: string | null) => (value ? userName(value) : <Typography.Text type="danger">{zh ? "未指定" : "Unassigned"}</Typography.Text>),
    },
    {
      title: "SLA", key: "sla", width: 100,
      render: (_: unknown, row: QualityAlert) => {
        const state = slaState(row);
        if (!state) return "-";
        return <Tag color={state.overdue ? "red" : undefined}>{state.overdue ? (zh ? "超时 " : "Overdue ") : ""}{state.text}</Tag>;
      },
    },
    {
      title: zh ? "操作" : "Actions", key: "actions", width: 150, fixed: "right" as const,
      render: (_: unknown, row: QualityAlert) => (
        <Space size={4}>
          {row.status === "open" && (
            <Button
              size="small" type="link" data-testid={`ack-${row.id}`}
              onClick={() => { setAssignee(undefined); setBatchTargets([row]); }}
            >
              {zh ? "确认" : "Ack"}
            </Button>
          )}
          <Button size="small" type="link" data-testid={`open-${row.id}`} onClick={() => openDisposition(row.id)}>
            {zh ? "处置" : "Handle"}
          </Button>
        </Space>
      ),
    },
  ];

  const selectedRows = rows.filter((row) => selected.includes(row.id) && row.status === "open");

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_alerts" testId="v2-quality-alerts">
        <PageHeading
          section="quality"
          navKey="quality_alerts"
          desc={zh
            ? "六类预警来源归一列表：筛选定位、确认并指定责任人、转处置工作台。同因预警在合并窗口内折叠成组。"
            : "Unified alert list: filter, acknowledge with a required assignee, hand over to the disposition workbench. Same-cause alerts fold into one group."}
          actions={
            <Space wrap>
              <Select
                aria-label={zh ? "选择项目" : "Select project"}
                style={{ minWidth: 180 }}
                placeholder={zh ? "选择项目" : "Select project"}
                value={projectId ?? undefined}
                onChange={(value: string) => { setProjectId(value); setPage(1); setSelected([]); }}
                options={projects.map((p) => ({ value: p.id, label: p.name }))}
              />
              <Select
                aria-label={zh ? "状态筛选" : "Status filter"} allowClear style={{ width: 120 }}
                placeholder={zh ? "状态" : "Status"} value={filters.status}
                onChange={(value: string | undefined) => { setFilters((f) => ({ ...f, status: value })); setPage(1); }}
                options={(Object.keys(ALERT_LABELS.status[lang]) as QualityAlert["status"][]).map((key) => ({ value: key, label: ALERT_LABELS.status[lang][key] }))}
              />
              <Select
                aria-label={zh ? "级别筛选" : "Severity filter"} allowClear style={{ width: 120 }}
                placeholder={zh ? "级别" : "Severity"} value={filters.severity}
                onChange={(value: string | undefined) => { setFilters((f) => ({ ...f, severity: value })); setPage(1); }}
                options={(Object.keys(ALERT_LABELS.severity[lang]) as QualityAlert["severity"][]).map((key) => ({ value: key, label: ALERT_LABELS.severity[lang][key] }))}
              />
              <Select
                aria-label={zh ? "来源筛选" : "Source filter"} allowClear style={{ width: 130 }}
                placeholder={zh ? "来源" : "Source"} value={filters.source_type}
                onChange={(value: string | undefined) => { setFilters((f) => ({ ...f, source_type: value })); setPage(1); }}
                options={(Object.keys(ALERT_LABELS.source[lang]) as QualityAlert["source_type"][]).map((key) => ({ value: key, label: ALERT_LABELS.source[lang][key] }))}
              />
              <Select
                aria-label={zh ? "场景筛选" : "Scene filter"} allowClear style={{ minWidth: 150 }}
                placeholder={zh ? "场景" : "Scene"} value={filters.scene_id}
                onChange={(value: string | undefined) => { setFilters((f) => ({ ...f, scene_id: value })); setPage(1); }}
                options={scenes.map((s) => ({ value: s.id, label: `${s.name}（${s.code}）` }))}
              />
              <Input
                aria-label={zh ? "样本键" : "Sample key"} allowClear style={{ width: 140 }}
                placeholder={zh ? "样本键" : "Sample key"}
                onPressEnter={(event) => { setFilters((f) => ({ ...f, sample_key: (event.target as HTMLInputElement).value })); setPage(1); }}
              />
              <Switch
                aria-label={zh ? "显示演示数据" : "Show demo data"}
                checked={Boolean(filters.include_demo)}
                checkedChildren={zh ? "含演示" : "Demo"}
                unCheckedChildren={zh ? "真实" : "Live"}
                onChange={(value) => { setFilters((f) => ({ ...f, include_demo: value })); setPage(1); }}
              />
              <Button icon={<DownloadOutlined />} onClick={exportCsv} data-testid="export-csv">{zh ? "导出 CSV" : "Export CSV"}</Button>
              <Button icon={<ReloadOutlined />} onClick={load}>{zh ? "刷新" : "Refresh"}</Button>
            </Space>
          }
        />
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={4}><Card size="small"><Statistic title={zh ? "待确认" : "Open"} value={summary.open} valueStyle={{ color: "#cf1322" }} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title={zh ? "处理中" : "Handling"} value={summary.handling} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title={zh ? "待复核" : "Review"} value={summary.review} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title={zh ? "SLA 超时" : "SLA overdue"} value={summary.overdue} valueStyle={{ color: summary.overdue > 0 ? "#cf1322" : undefined }} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title={zh ? "今日新增" : "New today"} value={summary.today} /></Card></Col>
          <Col span={4}>
            <Card size="small" style={{ height: "100%" }}>
              <Button type="link" style={{ padding: 0 }} onClick={() => navigate("/quality/sops?tab=rules")}>
                {zh ? "配置预警规则" : "Alert rules"}
              </Button>
            </Card>
          </Col>
        </Row>
        <Card
          extra={(
            <Button
              type="primary" data-testid="batch-ack" disabled={selectedRows.length === 0}
              onClick={() => { setAssignee(undefined); setBatchTargets(selectedRows); }}
            >
              {zh ? `批量确认（${selectedRows.length}）` : `Acknowledge (${selectedRows.length})`}
            </Button>
          )}
        >
          <Table
            rowKey="id"
            loading={loading}
            columns={columns}
            dataSource={rows}
            scroll={{ x: 1100 }}
            rowSelection={{
              selectedRowKeys: selected,
              onChange: setSelected,
              // 只有待确认的可以批量确认；已进入处置的不能被重复确认
              getCheckboxProps: (row) => ({ disabled: row.status !== "open" }),
            }}
            expandable={{
              rowExpandable: (row) => row.occurrence_count > 1,
              onExpand: (expanded, row) => { if (expanded) void loadOccurrences(row); },
              expandedRowRender: (row) => (
                <List
                  size="small"
                  data-testid={`occurrences-${row.id}`}
                  dataSource={occurrences[row.id] ?? []}
                  loading={!occurrences[row.id]}
                  locale={{ emptyText: zh ? "暂无明细" : "No occurrences" }}
                  renderItem={(event) => (
                    <List.Item>
                      <Space wrap>
                        <Typography.Text type="secondary">{formatLocalTime(event.created_at)}</Typography.Text>
                        <span>{zh ? "样本" : "sample"} {String(event.form_snapshot?.sample_key ?? "-")}</span>
                        {event.form_snapshot?.risk_score != null && <Tag>{String(event.form_snapshot.risk_score)}</Tag>}
                      </Space>
                    </List.Item>
                  )}
                />
              ),
            }}
            pagination={{
              current: page, pageSize, total, showSizeChanger: true,
              onChange: (nextPage, nextSize) => { setPage(nextPage); setPageSize(nextSize); },
            }}
            locale={{ emptyText: <Empty description={zh ? "暂无预警：推理越过触发阈值、参数超限或设备离线后在此出现" : "No alerts yet"} /> }}
          />
        </Card>
        {/* 诚实设计②：风险分口径脚注 */}
        <Typography.Paragraph type="secondary" style={{ marginTop: 12 }} data-testid="risk-footnote">
          {zh
            ? "风险分口径：有监督模型为预测概率；无监督模型为异常分数（量纲因族而异）或模型直接判异。预警触发下限独立于分级阈值（须满足 触发 ≤ 高 ≤ 严重），调整分级阈值不改变触发判定；触发下限、分级阈值、SLA 时长与合并窗口在「SOP 维护 › 预警规则」里按场景配置。演示数据默认不显示。"
            : "Risk score: predicted probability for supervised models; anomaly score (family-specific scale) or the model's own flag for unsupervised models. The trigger threshold is independent of severity thresholds (trigger ≤ high ≤ critical). Demo data is hidden by default."}
        </Typography.Paragraph>
        <Modal
          open={Boolean(batchTargets)}
          destroyOnClose
          title={zh ? `确认 ${batchTargets?.length ?? 0} 条预警` : `Acknowledge ${batchTargets?.length ?? 0} alerts`}
          okText={zh ? "确认" : "Acknowledge"}
          okButtonProps={{ disabled: !assignee, loading: busy }}
          onCancel={() => { setBatchTargets(null); setAssignee(undefined); }}
          onOk={() => { if (batchTargets) void confirmMany(batchTargets); }}
        >
          <Typography.Paragraph>
            {zh ? "确认前必须指定责任人——责任人为空时无法确认（避免预警无人认领）。" : "An assignee is required before acknowledging."}
          </Typography.Paragraph>
          <Select
            aria-label={zh ? "批量确认责任人" : "Batch assignee"}
            showSearch
            optionFilterProp="label"
            style={{ width: "100%" }}
            placeholder={zh ? "选择责任人（必填）" : "Assignee (required)"}
            value={assignee}
            onChange={setAssignee}
            options={people}
          />
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
