import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { App as AntApp, Button, Card, Col, Empty, Row, Select, Space, Statistic, Table, Tag, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { ScopeSelector, StaleBanner, durationText, percentText, useMonitorScope } from "../components/quality/MonitorParts";
import { getDashboard } from "../api/qualityMonitor";
import type { DashboardPayload } from "../api/qualityMonitor";
import { ALERT_LABELS, apiErrorText } from "../api/qualityAlerts";
import type { AlertSeverity } from "../api/qualityAlerts";
import { useI18n } from "../i18n";
import { formatLocalTime } from "../utils/time";

/** 质量管理 · 监控 / 质量驾驶舱（B1-03，技术方案 §9B.4）。
 *
 * 所有数字来自后端同一个聚合口径模块；KPI 卡可下钻到预警列表 / 生产记录 / 趋势页。
 */

const REFRESH_SECONDS = 30;

export default function QualityDashboardPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const navigate = useNavigate();
  const { projectId, setProjectId, projects, scenes, stations, scope, setLevel, options } = useMonitorScope();
  const [days, setDays] = useState(7);
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    if (!projectId) { setData(null); return; }
    setLoading(true);
    getDashboard(projectId, scope, days)
      .then(setData)
      .catch((e) => message.error(apiErrorText(e)))
      .finally(() => setLoading(false));
  }, [projectId, scope, days, message]);

  useEffect(() => { load(); }, [load]);
  // 驾驶舱按固定节奏整体刷新（推送流留给实时监控页）
  useEffect(() => {
    const timer = window.setInterval(() => { if (document.visibilityState !== "hidden") load(); }, REFRESH_SECONDS * 1000);
    return () => window.clearInterval(timer);
  }, [load]);

  const alerts = data?.alerts;
  const ops = data?.disposition_ops;
  const production = data?.production;

  // 逐层取值：接口返回体缺字段（如网关错误页）时显示 0，不让整页崩溃
  const kpis = [
    { key: "total", title: zh ? "产量" : "Produced", value: production?.total ?? 0, to: "/quality/production-records" },
    { key: "ok", title: zh ? "正常数" : "OK", value: production?.ok ?? 0, to: "/quality/production-records" },
    { key: "confirmed_ng", title: zh ? "已确认 NG" : "Confirmed NG", value: alerts?.confirmed_ng ?? 0, to: "/quality/alerts?status=closed", danger: true },
    { key: "alerts", title: zh ? "AI+SPC 预警" : "AI+SPC alerts", value: alerts?.alerts_in_window ?? 0, to: "/quality/alerts" },
    // 下钻链接与卡片数字同口径：待处理 = 未关闭（四个阶段），高风险 = 高风险 + 严重
    { key: "open", title: zh ? "待处理" : "Open", value: alerts?.open ?? 0, to: "/quality/alerts?open=1", danger: true },
    { key: "high", title: zh ? "高风险" : "High risk", value: alerts?.high_risk ?? 0, to: "/quality/alerts?min_severity=high", danger: true },
  ];

  const trendOption = useMemo(() => {
    const points = data?.trend?.points ?? [];
    return {
      tooltip: { trigger: "axis" },
      legend: { data: [zh ? "产量" : "Produced", zh ? "异常" : "Anomaly", zh ? "预警" : "Alerts", zh ? "确认 NG" : "Confirmed NG"] },
      grid: { left: 48, right: 16, top: 32, bottom: 28 },
      xAxis: { type: "category", data: points.map((point) => point.date.slice(5)) },
      yAxis: { type: "value", minInterval: 1 },
      series: [
        { name: zh ? "产量" : "Produced", type: "bar", data: points.map((point) => point.total), itemStyle: { color: "#1677ff" } },
        { name: zh ? "异常" : "Anomaly", type: "bar", data: points.map((point) => point.anomaly), itemStyle: { color: "#faad14" } },
        { name: zh ? "预警" : "Alerts", type: "line", data: points.map((point) => point.alerts), smooth: true },
        { name: zh ? "确认 NG" : "Confirmed NG", type: "line", data: points.map((point) => point.confirmed_ng), smooth: true, itemStyle: { color: "#cf1322" } },
      ],
    };
  }, [data, zh]);

  const riskOption = useMemo(() => {
    const bySeverity = alerts?.by_severity ?? {};
    return {
      tooltip: { trigger: "item" },
      legend: { bottom: 0 },
      series: [{
        type: "pie", radius: ["40%", "70%"], center: ["50%", "45%"],
        data: (["warning", "high", "critical"] as const).map((key) => ({
          name: ALERT_LABELS.severity[lang][key], value: bySeverity[key] ?? 0,
        })),
        label: { show: false },
      }],
    };
  }, [alerts, lang]);

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_dashboard" testId="v2-quality-dashboard">
        <PageHeading
          section="quality"
          navKey="quality_dashboard"
          desc={zh ? "质量 KPI 驾驶舱：产量、正常数、已确认 NG、预警、待处理、高风险。所有卡片按同一口径取数，可下钻到列表。" : "Quality KPI cockpit. Every card shares one aggregate definition and drills down to a list."}
          actions={(
            <Space wrap>
              <Select
                aria-label={zh ? "选择项目" : "Select project"}
                style={{ minWidth: 180 }}
                placeholder={zh ? "选择项目" : "Select project"}
                value={projectId ?? undefined}
                onChange={(value: string) => setProjectId(value)}
                options={projects.map((p) => ({ value: p.id, label: p.name }))}
              />
              <ScopeSelector scope={scope} options={options} scenes={scenes} stations={stations} onChange={setLevel} />
              <Select
                aria-label={zh ? "时间窗" : "Window"}
                style={{ width: 110 }}
                value={days}
                onChange={setDays}
                options={[7, 14, 30, 90].map((value) => ({ value, label: zh ? `近 ${value} 天` : `${value}d` }))}
              />
              <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>{zh ? "刷新" : "Refresh"}</Button>
            </Space>
          )}
        />
        <StaleBanner stale={data?.stale} />
        <Row gutter={[16, 16]}>
          {kpis.map((kpi) => (
            <Col span={4} key={kpi.key}>
              <Card
                hoverable
                size="small"
                data-testid={`kpi-${kpi.key}`}
                onClick={() => navigate(kpi.to)}
              >
                <Statistic
                  title={kpi.title}
                  value={kpi.value}
                  valueStyle={kpi.danger && kpi.value > 0 ? { color: "#cf1322" } : undefined}
                />
              </Card>
            </Col>
          ))}
        </Row>
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col span={24}>
            <Card size="small" title={zh ? "处置运营" : "Disposition operations"} data-testid="disposition-ops">
              <Space size="large" wrap>
                <Statistic title={zh ? "每千件处置单数" : "Dispositions per 1k"} value={ops?.per_thousand ?? undefined} precision={2} suffix="‰" />
                <Statistic title={zh ? "首次处理均时" : "Mean time to first handle"} formatter={() => durationText(ops?.mean_first_ack_seconds, zh)} />
                <Statistic title={zh ? "结案率" : "Closure rate"} formatter={() => percentText(ops?.closure_rate)} />
              </Space>
            </Card>
          </Col>
          <Col xs={24} lg={15}>
            <Card size="small" title={zh ? `近 ${days} 天走势` : `Last ${days} days`}>
              <ReactECharts notMerge style={{ height: 280 }} option={trendOption} />
            </Card>
          </Col>
          <Col xs={24} lg={9}>
            <Card size="small" title={zh ? "风险分布（窗内预警）" : "Risk distribution"}>
              <ReactECharts notMerge style={{ height: 280 }} option={riskOption} />
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card size="small" title={zh ? "最近异常" : "Recent alerts"} styles={{ body: { padding: 0 } }}>
              <Table
                rowKey="id" size="small" pagination={false}
                dataSource={data?.recent ?? []}
                onRow={(row) => ({ onClick: () => navigate(`/quality/disposition?alert=${row.id}`), style: { cursor: "pointer" } })}
                columns={[
                  { title: zh ? "时间" : "Time", dataIndex: "created_at", width: 150, render: (value: string | null) => (value ? formatLocalTime(value) : "-") },
                  { title: zh ? "预警" : "Alert", dataIndex: "title", ellipsis: true },
                  {
                    title: zh ? "级别" : "Severity", dataIndex: "severity", width: 90,
                    render: (value: AlertSeverity) => (
                      <Tag color={value === "critical" ? "red" : value === "high" ? "orange" : "gold"}>{ALERT_LABELS.severity[lang][value]}</Tag>
                    ),
                  },
                ]}
                locale={{ emptyText: zh ? "暂无预警" : "No alerts" }}
              />
            </Card>
          </Col>
          <Col xs={24} lg={6}>
            <Card size="small" title={zh ? "工位风险排名" : "Station ranking"}>
              <Table
                rowKey="station_id" size="small" pagination={false}
                dataSource={data?.station_ranking ?? []}
                onRow={(row) => ({ onClick: () => setLevel("station_id", row.station_id), style: { cursor: "pointer" } })}
                columns={[
                  { title: zh ? "工位" : "Station", dataIndex: "station", ellipsis: true },
                  { title: zh ? "未关闭" : "Open", dataIndex: "open", width: 70 },
                  { title: zh ? "高风险" : "High", dataIndex: "high_risk", width: 70, render: (value: number) => (value > 0 ? <Tag color="red">{value}</Tag> : value) },
                ]}
                locale={{ emptyText: zh ? "暂无预警" : "No alerts" }}
              />
            </Card>
          </Col>
          <Col xs={24} lg={6}>
            <Card size="small" title={zh ? "产线状态分布" : "Line status"}>
              <Table
                rowKey="line" size="small" pagination={false}
                dataSource={data?.line_status ?? []}
                onRow={(row) => ({ onClick: () => setLevel("production_line", row.line === "未归属产线" ? undefined : row.line), style: { cursor: "pointer" } })}
                columns={[
                  { title: zh ? "产线" : "Line", dataIndex: "line", ellipsis: true },
                  { title: zh ? "工位" : "Stations", dataIndex: "stations", width: 60 },
                  { title: zh ? "有预警" : "Alerting", dataIndex: "stations_with_open_alerts", width: 70 },
                  { title: zh ? "离线设备" : "Offline", dataIndex: "offline_devices", width: 80, render: (value: number) => (value > 0 ? <Tag color="red">{value}</Tag> : value) },
                ]}
                locale={{ emptyText: <Empty description={zh ? "范围内没有启用的工位：先在「工位与设备」里登记工位并填写产线归属" : "No enabled stations in scope"} /> }}
              />
            </Card>
          </Col>
        </Row>
        {/* 诚实设计②：口径脚注 */}
        <Typography.Paragraph type="secondary" style={{ marginTop: 12 }} data-testid="dashboard-footnote">
          {zh
            ? `口径：命中率 = 已确认异常 ÷ 已关闭预警（本窗 ${percentText(alerts?.hit_rate)}）；已确认 NG 按预警的发生次数计；产量读小时聚合桶。每 ${REFRESH_SECONDS} 秒自动刷新。`
            : `Hit rate = confirmed issues ÷ closed alerts (${percentText(alerts?.hit_rate)}). Confirmed NG counts alert occurrences. Demo data is excluded. Auto-refresh every ${REFRESH_SECONDS}s.`}
        </Typography.Paragraph>
      </V2PageFrame>
    </AppLayout>
  );
}
