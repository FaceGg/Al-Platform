import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App as AntApp, Button, Card, Col, Empty, Input, Radio, Row, Select, Space, Statistic, Table, Tag, Typography,
} from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { ScopeSelector, StaleBanner, percentText, useMonitorScope } from "../components/quality/MonitorParts";
import { getTrends, saveNgVocabulary } from "../api/qualityMonitor";
import type { StaleState, TrendsPayload } from "../api/qualityMonitor";
import { apiErrorText } from "../api/qualityAlerts";
import { useI18n } from "../i18n";

/** 质量管理 · 分析 / 趋势与帕累托（B1-04，技术方案 §9B.4）。
 *
 * 走势与帕累托读聚合桶与预警表，切换对比维度不扫推理明细；NG 词表与质量报告共用一份。
 */

const DIMENSIONS = ["defect", "station", "device", "product", "batch"] as const;
type Dimension = (typeof DIMENSIONS)[number];

export default function QualityTrendsPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projectId, setProjectId, projects, scenes, stations, scope, setLevel, options } = useMonitorScope();
  const [days, setDays] = useState<7 | 30 | 90>(7);
  const [dimension, setDimension] = useState<Dimension>("defect");
  const [data, setData] = useState<TrendsPayload | null>(null);
  const [stale, setStale] = useState<StaleState | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [newLabel, setNewLabel] = useState("");
  const [newCategory, setNewCategory] = useState("");
  const [busy, setBusy] = useState(false);
  const role = localStorage.getItem("role");
  const canManage = role === "owner" || role === "editor";

  const load = useCallback(() => {
    if (!projectId) { setData(null); setStale(null); return; }
    getTrends(projectId, scope, days, dimension)
      .then((payload) => { setData(payload); setStale(payload.stale); setDraft(payload.ng_vocabulary); })
      .catch((e) => message.error(apiErrorText(e)));
  }, [projectId, scope, days, dimension, message]);

  useEffect(() => { load(); }, [load]);

  // 逐层取值：返回体缺字段时按空数据处理，不让整页崩溃
  const totals = data?.trend?.totals;

  const trendOption = useMemo(() => {
    const points = data?.trend?.points ?? [];
    return {
      tooltip: { trigger: "axis" },
      legend: { data: [zh ? "NG 率" : "NG rate", zh ? "预警" : "Alerts", zh ? "SPC 超限" : "SPC exceed"] },
      grid: { left: 56, right: 16, top: 32, bottom: 28 },
      xAxis: { type: "category", data: points.map((point) => point.date.slice(5)) },
      yAxis: [
        { type: "value", minInterval: 1, name: zh ? "条" : "count" },
        { type: "value", axisLabel: { formatter: "{value}%" }, max: 100 },
      ],
      series: [
        { name: zh ? "预警" : "Alerts", type: "bar", data: points.map((point) => point.alerts) },
        { name: zh ? "SPC 超限" : "SPC exceed", type: "bar", data: points.map((point) => point.spc_exceed) },
        {
          name: zh ? "NG 率" : "NG rate", type: "line", yAxisIndex: 1, smooth: true,
          data: points.map((point) => (point.ng_rate === null ? null : +(point.ng_rate * 100).toFixed(2))),
        },
      ],
    };
  }, [data, zh]);

  const dimensionLabel: Record<Dimension, string> = {
    defect: zh ? "缺陷" : "Defect", station: zh ? "工位" : "Station", device: zh ? "设备" : "Device",
    product: zh ? "产品" : "Product", batch: zh ? "批次" : "Batch",
  };

  const paretoOption = useMemo(() => {
    const items = data?.pareto?.items ?? [];
    return {
      tooltip: { trigger: "axis" },
      legend: { data: [zh ? "发生次数" : "Occurrences", zh ? "累计占比" : "Cumulative"] },
      grid: { left: 56, right: 56, top: 32, bottom: 64 },
      xAxis: { type: "category", data: items.map((item) => item.label), axisLabel: { rotate: 30, interval: 0 } },
      yAxis: [
        { type: "value", minInterval: 1 },
        { type: "value", axisLabel: { formatter: "{value}%" }, max: 100 },
      ],
      series: [
        { name: zh ? "发生次数" : "Occurrences", type: "bar", data: items.map((item) => item.count) },
        {
          name: zh ? "累计占比" : "Cumulative", type: "line", yAxisIndex: 1,
          data: items.map((item) => +(item.cumulative * 100).toFixed(1)),
        },
      ],
    };
  }, [data, zh]);

  const save = async () => {
    setBusy(true);
    try {
      await saveNgVocabulary(projectId!, draft);
      message.success(zh ? "NG 词表已保存" : "NG vocabulary saved");
      load();
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const addEntry = () => {
    const label = newLabel.trim();
    if (!label) return;
    setDraft((current) => ({ ...current, [label]: newCategory.trim() }));
    setNewLabel("");
    setNewCategory("");
  };

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_trends" testId="v2-quality-trends">
        <PageHeading
          section="quality"
          navKey="quality_trends"
          desc={zh ? "质量趋势与帕累托：NG 率走势、SPC 超限统计、缺陷帕累托；可按工位 / 设备 / 产品 / 批次切换对比维度。" : "Quality trends and Pareto analysis with switchable comparison dimensions."}
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
              <Radio.Group
                aria-label={zh ? "时间窗" : "Window"}
                optionType="button"
                value={days}
                onChange={(event) => setDays(event.target.value)}
                options={[7, 30, 90].map((value) => ({ value, label: zh ? `${value} 天` : `${value}d` }))}
              />
              <Button icon={<ReloadOutlined />} onClick={load}>{zh ? "刷新" : "Refresh"}</Button>
              <Button onClick={() => window.print()} data-testid="print-report">{zh ? "导出 / 打印" : "Export / print"}</Button>
            </Space>
          )}
        />
        <StaleBanner stale={stale} />
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col span={6}><Card size="small"><Statistic title={zh ? "产量" : "Produced"} value={totals?.total ?? 0} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title={zh ? "已确认 NG" : "Confirmed NG"} value={totals?.confirmed_ng ?? 0} valueStyle={{ color: "#cf1322" }} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title={zh ? "NG 率" : "NG rate"} formatter={() => percentText(totals?.ng_rate)} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title={zh ? "SPC 超限" : "SPC exceed"} value={totals?.spc_exceed ?? 0} /></Card></Col>
        </Row>
        <Row gutter={[16, 16]}>
          <Col span={24}>
            <Card size="small" title={zh ? `近 ${days} 天 NG 率走势与超限统计` : `NG rate and exceedances (${days}d)`} data-testid="trend-chart">
              <ReactECharts notMerge style={{ height: 300 }} option={trendOption} />
            </Card>
          </Col>
          <Col xs={24} lg={15}>
            <Card
              size="small"
              data-testid="pareto-chart"
              title={zh ? `帕累托（按${dimensionLabel[dimension]}，按发生次数）` : `Pareto by ${dimensionLabel[dimension]}`}
              extra={(
                <Radio.Group
                  aria-label={zh ? "对比维度" : "Dimension"}
                  optionType="button"
                  size="small"
                  value={dimension}
                  onChange={(event) => setDimension(event.target.value)}
                  options={DIMENSIONS.map((value) => ({ value, label: dimensionLabel[value] }))}
                />
              )}
            >
              <ReactECharts notMerge style={{ height: 300 }} option={paretoOption} />
            </Card>
          </Col>
          <Col xs={24} lg={9}>
            <Card
              size="small"
              data-testid="ng-vocabulary"
              title={zh ? "NG 词表（预测标签 → 缺陷类别）" : "NG vocabulary"}
              extra={canManage && (
                <Button type="primary" size="small" loading={busy} onClick={() => void save()} data-testid="save-vocabulary">
                  {zh ? "保存" : "Save"}
                </Button>
              )}
            >
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                {zh ? "词表与质量报告共用一份；未登记的预测标签在帕累托里归「未标注预测标签」。" : "Shared with quality reports; unmapped labels are grouped as unlabeled."}
              </Typography.Paragraph>
              <Table
                rowKey="label"
                size="small"
                pagination={false}
                dataSource={Object.entries(draft).map(([label, category]) => ({ label, category }))}
                columns={[
                  { title: zh ? "预测标签" : "Label", dataIndex: "label" },
                  {
                    title: zh ? "缺陷类别" : "Category", dataIndex: "category",
                    render: (value: string, row: { label: string }) => (canManage ? (
                      <Input
                        aria-label={`${zh ? "缺陷类别" : "Category"} ${row.label}`}
                        value={value}
                        maxLength={64}
                        onChange={(event) => setDraft((current) => ({ ...current, [row.label]: event.target.value }))}
                      />
                    ) : (value || "-")),
                  },
                ]}
                locale={{ emptyText: zh ? "暂无词表" : "No entries" }}
              />
              {canManage && (
                <Space style={{ marginTop: 12 }} wrap>
                  <Input
                    aria-label={zh ? "新标签" : "New label"}
                    style={{ width: 150 }}
                    placeholder={zh ? "预测标签" : "Label"}
                    value={newLabel}
                    maxLength={128}
                    onChange={(event) => setNewLabel(event.target.value)}
                  />
                  <Input
                    aria-label={zh ? "新缺陷类别" : "New category"}
                    style={{ width: 150 }}
                    placeholder={zh ? "缺陷类别" : "Category"}
                    value={newCategory}
                    maxLength={64}
                    onChange={(event) => setNewCategory(event.target.value)}
                  />
                  <Button size="small" onClick={addEntry} data-testid="add-vocabulary">{zh ? "添加" : "Add"}</Button>
                </Space>
              )}
            </Card>
          </Col>
        </Row>
        {/* 诚实设计②：口径脚注 */}
        <Typography.Paragraph type="secondary" style={{ marginTop: 12 }} data-testid="trends-footnote">
          {zh
            ? "口径：NG 率 = 已确认 NG ÷ 产量，按自然日计；已确认 NG 按预警的发生次数计（同因合并后一条预警可代表多个样本）；SPC 超限 = 参数超限与 SPC 判异类预警；产量读小时聚合桶。切换对比维度只读预警表，不扫推理明细。"
            : "NG rate = confirmed NG ÷ produced per calendar day; confirmed NG counts alert occurrences; SPC exceed = parameter-limit and SPC alerts."}
        </Typography.Paragraph>
        {data?.pareto?.items?.length === 0 && (
          <Empty description={zh ? "时间窗内没有预警：产生预警后帕累托在此出现" : "No alerts in this window"} />
        )}
      </V2PageFrame>
    </AppLayout>
  );
}
