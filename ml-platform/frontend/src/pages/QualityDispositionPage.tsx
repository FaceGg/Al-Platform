import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  App as AntApp, Button, Card, Col, Empty, Radio, Row, Select, Space, Statistic, Table, Tag, Typography,
} from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import AlertDispositionDrawer from "../components/quality/AlertDispositionDrawer";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import { ALERT_LABELS, STATUS_COLOR, alertEvidenceText, apiErrorText, listQualityAlerts, slaState } from "../api/qualityAlerts";
import type { QualityAlert } from "../api/qualityAlerts";
import apiClient from "../api/client";
import { useI18n } from "../i18n";
import { formatLocalTime } from "../utils/time";

/** 质量管理 · 监控 / 处置工作台（B1-02，技术方案 §9.8）。
 *
 * 列出进入处置的预警（已确认 / 处理中 / 待复核）与已关闭的单子；点开行进入处置抽屉。
 * 预警中心通过 `?alert=<id>` 直达某条预警。
 */

type Scope = "handling" | "mine" | "all" | "closed";

export default function QualityDispositionPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [searchParams, setSearchParams] = useSearchParams();
  const lookups = useQualityAlertLookups();
  const { projectId, setProjectId, projects, people, sceneName, stationName, userName } = lookups;
  const [rows, setRows] = useState<QualityAlert[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [scope, setScope] = useState<Scope>("handling");
  const [sceneId, setSceneId] = useState<string | undefined>(undefined);
  const [counts, setCounts] = useState({ handling: 0, review: 0, closed: 0, overdue: 0 });
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [activeAlertId, setActiveAlertId] = useState<string | null>(null);

  // 预警中心跳转过来时直接打开对应预警的处置抽屉
  useEffect(() => {
    const target = searchParams.get("alert");
    if (target) setActiveAlertId(target);
  }, [searchParams]);

  useEffect(() => {
    apiClient.get("/auth/me").then((res) => setCurrentUserId(String(res.data?.id ?? "")))
      .catch(() => setCurrentUserId(null));
  }, []);

  // 处置中的单子按状态分四次取（接口的状态筛选是单值）
  const load = useCallback(() => {
    if (!projectId) { setRows([]); setTotal(0); return; }
    setLoading(true);
    const statuses = scope === "handling"
      ? ["acknowledged", "processing", "review_pending"]
      : scope === "closed" ? ["closed"] : ["open", "acknowledged", "processing", "review_pending", "closed"];
    Promise.all(statuses.map((status) => listQualityAlerts(projectId, {
      status, scene_id: sceneId, page: 1, page_size: 100,
    }))).then((pages) => {
      let merged = pages.flatMap((result) => result.items);
      // 「我负责的」在客户端过滤：接口没有按责任人筛选的参数
      if (scope === "mine") merged = merged.filter((item) => item.assigned_to === currentUserId);
      merged.sort((a, b) => String(b.last_event_at ?? "").localeCompare(String(a.last_event_at ?? "")));
      setRows(merged.slice((page - 1) * pageSize, page * pageSize));
      setTotal(merged.length);
    }).catch((e) => message.error(apiErrorText(e)))
      .finally(() => setLoading(false));
  }, [projectId, scope, sceneId, page, pageSize, currentUserId, message]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!projectId) return;
    const count = async (status: string) => {
      try { return (await listQualityAlerts(projectId, { status, page_size: 1 })).total; } catch { return 0; }
    };
    void Promise.all([
      count("acknowledged"), count("processing"), count("review_pending"), count("closed"),
      listQualityAlerts(projectId, { sla_overdue: true, page_size: 1 }).then((result) => result.total).catch(() => 0),
    ]).then(([acknowledged, processing, review, closed, overdue]) => {
      setCounts({ handling: acknowledged + processing, review, closed, overdue });
    });
  }, [projectId, total, load]);

  const closeDrawer = () => {
    setActiveAlertId(null);
    if (searchParams.get("alert")) {
      const next = new URLSearchParams(searchParams);
      next.delete("alert");
      setSearchParams(next, { replace: true });
    }
  };

  const columns = [
    {
      title: zh ? "最近动态" : "Last activity", dataIndex: "last_event_at", key: "last_event_at", width: 170,
      render: (value: string | null) => (value ? formatLocalTime(value) : "-"),
    },
    {
      title: zh ? "预警" : "Alert", key: "title",
      render: (_: unknown, row: QualityAlert) => (
        <Space direction="vertical" size={0}>
          <span>{row.title}{row.occurrence_count > 1 ? ` ×${row.occurrence_count}` : ""}</span>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{alertEvidenceText(row, zh)}</Typography.Text>
        </Space>
      ),
    },
    {
      title: zh ? "场景 / 工位" : "Scene / station", key: "scope", width: 200,
      render: (_: unknown, row: QualityAlert) => `${sceneName(row.scene_id)} / ${stationName(row.station_id)}`,
    },
    {
      title: zh ? "阶段" : "Stage", dataIndex: "status", key: "status", width: 100,
      render: (value: QualityAlert["status"]) => <Tag color={STATUS_COLOR[value]}>{ALERT_LABELS.status[lang][value]}</Tag>,
    },
    {
      title: zh ? "责任人" : "Assignee", dataIndex: "assigned_to", key: "assigned_to", width: 110,
      render: (value: string | null) => userName(value),
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
      title: zh ? "关闭结论" : "Resolution", dataIndex: "resolution", key: "resolution", width: 100,
      render: (value: string | null) => (value ? (ALERT_LABELS.resolution[lang] as Record<string, string>)[value] ?? value : "-"),
    },
    {
      title: zh ? "操作" : "Actions", key: "actions", width: 90, fixed: "right" as const,
      render: (_: unknown, row: QualityAlert) => (
        <Button size="small" type="link" data-testid={`dispose-${row.id}`} onClick={() => setActiveAlertId(row.id)}>
          {row.status === "closed" ? (zh ? "查看" : "View") : (zh ? "处置" : "Handle")}
        </Button>
      ),
    },
  ];

  const scopeOptions = [
    { value: "handling", label: zh ? "处置中" : "In handling" },
    { value: "mine", label: zh ? "我负责的" : "Mine" },
    { value: "all", label: zh ? "全部" : "All" },
    { value: "closed", label: zh ? "已关闭" : "Closed" },
  ];

  const emptyText = useMemo(() => {
    if (scope === "handling") return zh ? "暂无处置中的预警：在预警中心确认后，预警会进入这里" : "No alerts in handling";
    if (scope === "mine") return zh ? "没有指派给你的预警" : "Nothing assigned to you";
    return zh ? "暂无记录" : "No records";
  }, [scope, zh]);

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_disposition" testId="v2-quality-disposition">
        <PageHeading
          section="quality"
          navKey="quality_disposition"
          desc={zh
            ? "单预警五阶段流转：待确认 → 已确认 → 处理中 → 待复核 → 已关闭；证据区并列实测值、基线、规格上下限与模型依据。"
            : "Five-stage disposition per alert with measured value, baseline, spec limits and model basis side by side."}
          actions={
            <Space wrap>
              <Select
                aria-label={zh ? "选择项目" : "Select project"}
                style={{ minWidth: 180 }}
                placeholder={zh ? "选择项目" : "Select project"}
                value={projectId ?? undefined}
                onChange={(value: string) => { setProjectId(value); setPage(1); }}
                options={projects.map((p) => ({ value: p.id, label: p.name }))}
              />
              <Radio.Group
                optionType="button"
                buttonStyle="solid"
                value={scope}
                onChange={(event) => { setScope(event.target.value as Scope); setPage(1); }}
                options={scopeOptions}
              />
              <Select
                aria-label={zh ? "场景筛选" : "Scene filter"} allowClear style={{ minWidth: 150 }}
                placeholder={zh ? "场景" : "Scene"} value={sceneId}
                onChange={(value: string | undefined) => { setSceneId(value); setPage(1); }}
                options={lookups.scenes.map((s) => ({ value: s.id, label: `${s.name}（${s.code}）` }))}
              />
              <Button icon={<ReloadOutlined />} onClick={load}>{zh ? "刷新" : "Refresh"}</Button>
            </Space>
          }
        />
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}><Card size="small"><Statistic title={zh ? "处置中" : "In handling"} value={counts.handling} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title={zh ? "待复核" : "Review pending"} value={counts.review} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title={zh ? "SLA 超时" : "SLA overdue"} value={counts.overdue} valueStyle={{ color: counts.overdue > 0 ? "#cf1322" : undefined }} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title={zh ? "已关闭" : "Closed"} value={counts.closed} /></Card></Col>
        </Row>
        <Card>
          <Table
            rowKey="id"
            loading={loading}
            columns={columns}
            dataSource={rows}
            scroll={{ x: 1100 }}
            pagination={{
              current: page, pageSize, total, showSizeChanger: true,
              onChange: (nextPage, nextSize) => { setPage(nextPage); setPageSize(nextSize); },
            }}
            locale={{ emptyText: <Empty description={emptyText} /> }}
          />
        </Card>
        <AlertDispositionDrawer
          projectId={projectId ?? ""}
          alertId={activeAlertId}
          assigneeOptions={people}
          stationName={stationName}
          sceneName={sceneName}
          onClose={closeDrawer}
          onChanged={load}
        />
      </V2PageFrame>
    </AppLayout>
  );
}
