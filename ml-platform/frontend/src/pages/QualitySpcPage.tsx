import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App as AntApp, Button, Card, Col, Empty, InputNumber, Row, Select, Space, Statistic, Switch,
  Table, Tag, Typography,
} from "antd";
import { ReloadOutlined, ThunderboltOutlined } from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import { listDatasetVersions } from "../api/datasets";
import type { DatasetVersionOption } from "../api/datasets";
import {
  analyzeSpc, getSpcFields,
} from "../api/qualitySpc";
import type { SpcAnalysisResult, SpcChartKind, SpcField, SpcSource } from "../api/qualitySpc";
import { apiErrorText } from "../api/qualityAlerts";
import { useI18n } from "../i18n";

/** 质量管理 · 分析 / SPC 过程控制（B1-06，技术方案 §9C）。
 *
 * 数据源二选一（数据集版本字段 / 推理结果数值列）；控制图 + 判异明细 + 直方图 + 能力指数；
 * 判异点可登记为 SPC 判异类预警（预警中心可跳回本页按样本键定位）。
 */

const CHART_OPTIONS: { value: SpcChartKind; zh: string; en: string; variable: boolean }[] = [
  { value: "i_mr", zh: "I-MR（单值）", en: "I-MR", variable: true },
  { value: "xbar_r", zh: "X̄-R（子群）", en: "X̄-R", variable: true },
  { value: "xbar_s", zh: "X̄-S（子群）", en: "X̄-S", variable: true },
  { value: "p", zh: "P（不合格率）", en: "P", variable: false },
  { value: "np", zh: "NP（不合格数）", en: "NP", variable: false },
  { value: "c", zh: "C（缺陷数）", en: "C", variable: false },
  { value: "u", zh: "U（单位缺陷）", en: "U", variable: false },
];

const RULE_TEXT: Record<number, string> = {
  1: "1 点越出 3σ", 2: "连续 9 点同侧", 3: "连续 6 点单调", 4: "连续 14 点交替",
  5: "3 点中 2 点越 2σ", 6: "5 点中 4 点越 1σ", 7: "连续 15 点在 1σ 内", 8: "连续 8 点在 1σ 外",
};

const CAPABILITY_LABELS: Record<string, string> = {
  cp: "Cp（组内）", cpk: "Cpk（组内）", pp: "Pp（整体）", ppk: "Ppk（整体）",
  cpm: "Cpm", cr: "Cr", sigma_level: "σ 水平", ppm: "估计 PPM",
};

export default function QualitySpcPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projectId, setProjectId, projects, scenes, stations } = useQualityAlertLookups();
  const [source, setSource] = useState<SpcSource>("dataset");
  const [datasetVersions, setDatasetVersions] = useState<DatasetVersionOption[]>([]);
  const [datasetVersionId, setDatasetVersionId] = useState<string | undefined>(undefined);
  const [fields, setFields] = useState<SpcField[]>([]);
  const [field, setField] = useState<string | undefined>(undefined);
  const [chart, setChart] = useState<SpcChartKind>("i_mr");
  const [subgroupSize, setSubgroupSize] = useState(5);
  const [sceneId, setSceneId] = useState<string | undefined>(undefined);
  const [stationId, setStationId] = useState<string | undefined>(undefined);
  const [usl, setUsl] = useState<number | undefined>(undefined);
  const [lsl, setLsl] = useState<number | undefined>(undefined);
  const [target, setTarget] = useState<number | undefined>(undefined);
  const [useSceneSpec, setUseSceneSpec] = useState(true);
  const [result, setResult] = useState<SpcAnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [raiseAlerts, setRaiseAlerts] = useState(false);
  const role = localStorage.getItem("role");
  const canHandle = role === "owner" || role === "editor" || role === "operator";

  useEffect(() => {
    if (!projectId) { setDatasetVersions([]); setFields([]); return; }
    listDatasetVersions(projectId).then(setDatasetVersions).catch(() => setDatasetVersions([]));
  }, [projectId]);

  const loadFields = useCallback(() => {
    if (!projectId) { setFields([]); return; }
    getSpcFields(projectId, source, datasetVersionId)
      .then((items) => {
        setFields(items);
        setField((current) => (current && items.some((item) => item.name === current) ? current : undefined));
      })
      .catch((e) => message.error(apiErrorText(e)));
  }, [projectId, source, datasetVersionId, message]);

  useEffect(() => { loadFields(); }, [loadFields]);

  const run = async () => {
    if (!projectId || !field) return;
    setLoading(true);
    try {
      setResult(await analyzeSpc(projectId, {
        source, field, chart, dataset_version_id: datasetVersionId ?? null,
        scene_id: sceneId ?? null, station_id: stationId ?? null,
        subgroup_size: subgroupSize, usl: usl ?? null, lsl: lsl ?? null, target: target ?? null,
        use_scene_spec: useSceneSpec, raise_alerts: raiseAlerts && canHandle,
      }));
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setLoading(false);
    }
  };

  const controlOption = useMemo(() => {
    const chartName = Object.keys(result?.charts ?? {})[0];
    const payload = chartName ? result?.charts[chartName] : undefined;
    if (!payload) return null;
    const labels = payload.points.map((point) => (point.occurred_at ? point.occurred_at.slice(5, 16) : `#${point.index}`));
    return {
      grid: { left: 56, right: 20, top: 40, bottom: 56 },
      legend: { data: [zh ? "测量值" : "Value", "UCL", zh ? "中心线" : "Center", "LCL"] },
      xAxis: { type: "category", data: labels, axisLabel: { rotate: 30, interval: 0 } },
      yAxis: { type: "value", scale: true },
      series: [
        {
          name: zh ? "测量值" : "Value", type: "line", data: payload.points.map((point) => point.value),
          symbol: "circle", symbolSize: 7,
          itemStyle: { color: (params: { dataIndex: number }) =>
            (payload.points[params.dataIndex]?.violations.length ? "#cf1322" : "#1677ff") },
          markLine: {
            silent: true, symbol: "none",
            data: [
              { yAxis: payload.ucl, name: "UCL", lineStyle: { color: "#cf1322", type: "dashed" } },
              { yAxis: payload.center, name: zh ? "中心线" : "Center", lineStyle: { color: "#1677ff" } },
              { yAxis: payload.lcl, name: "LCL", lineStyle: { color: "#cf1322", type: "dashed" } },
            ],
            label: { formatter: (params: { name: string }) => params.name },
          },
        },
      ],
      tooltip: { trigger: "axis" },
    };
  }, [result, zh]);

  const histogramOption = useMemo(() => {
    if (!result?.histogram.edges.length) return null;
    const counts = result.histogram.counts.map((count, index) => ({
      value: count,
      itemStyle: {
        // 规格带外的箱标红（有规格限时）
        color: result.spec.usl != null && result.histogram.edges[index + 1] > result.spec.usl
          ? "#ffc069" : result.spec.lsl != null && result.histogram.edges[index] < result.spec.lsl
            ? "#ffc069" : "#1677ff",
      },
    }));
    return {
      grid: { left: 48, right: 16, top: 24, bottom: 40 },
      xAxis: { type: "category", data: result.histogram.edges.slice(0, -1).map((edge, index) =>
        `${edge.toFixed(2)}~${result.histogram.edges[index + 1].toFixed(2)}`), axisLabel: { rotate: 30, fontSize: 10 } },
      yAxis: { type: "value", minInterval: 1 },
      series: [{ type: "bar", data: counts, barCategoryGap: "8%" }],
      tooltip: { trigger: "axis" },
    };
  }, [result]);

  const capabilityEntries = Object.entries(CAPABILITY_LABELS).map(([key, label]) => [
    label, result?.capability ? result.capability[key as keyof NonNullable<SpcAnalysisResult["capability"]>] : null,
  ] as [string, unknown]);

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_spc" testId="v2-quality-spc-page">
        <PageHeading
          section="quality"
          navKey="quality_spc"
          desc={zh
            ? "SPC 过程控制：变量图（I-MR / X̄-R / X̄-S）与计数图（P / NP / C / U），Nelson 1–8 判异，能力指数全套；规格限优先取场景规格定义。"
            : "SPC control charts with Nelson rules 1–8 and full capability indices; spec limits prefer the scene definition."}
          actions={(
            <Space wrap>
              <Select
                aria-label={zh ? "选择项目" : "Select project"} style={{ minWidth: 170 }}
                placeholder={zh ? "选择项目" : "Project"} value={projectId ?? undefined}
                onChange={(value: string) => { setProjectId(value); setResult(null); }}
                options={projects.map((item) => ({ value: item.id, label: item.name }))}
              />
              <Select
                aria-label={zh ? "数据来源" : "Source"} style={{ width: 130 }} value={source}
                onChange={(value: SpcSource) => { setSource(value); setField(undefined); setResult(null); }}
                options={[
                  { value: "dataset", label: zh ? "数据集版本" : "Dataset version" },
                  { value: "inference", label: zh ? "推理结果" : "Inference results" },
                ]}
              />
              {source === "dataset" && (
                <Select
                  aria-label={zh ? "数据集版本" : "Dataset version"} style={{ minWidth: 170 }} showSearch
                  optionFilterProp="label" placeholder={zh ? "数据集版本" : "Dataset"}
                  value={datasetVersionId}
                  onChange={(value: string) => { setDatasetVersionId(value); setField(undefined); setResult(null); }}
                  options={datasetVersions.map((version) => ({
                    value: version.id,
                    label: `v${version.version} · ${version.source_name ?? ""} · ${version.row_count} ${zh ? "行" : "rows"}`,
                  }))}
                />
              )}
              <Select
                aria-label={zh ? "过程参数" : "Field"} style={{ minWidth: 160 }} showSearch
                optionFilterProp="label" placeholder={zh ? "过程参数" : "Field"} value={field}
                onChange={setField}
                options={fields.filter((item) => item.numeric).map((item) => ({
                  value: item.name, label: item.label ? `${item.label}（${item.name}）` : item.name,
                }))}
              />
              <Select
                aria-label={zh ? "控制图" : "Chart"} style={{ width: 150 }} value={chart}
                onChange={(value: SpcChartKind) => setChart(value)}
                options={CHART_OPTIONS.map((option) => ({ value: option.value, label: zh ? option.zh : option.en }))}
              />
              {chart !== "i_mr" && (
                <Select
                  aria-label={zh ? "子群容量" : "Subgroup size"} style={{ width: 120 }} value={subgroupSize}
                  onChange={(value: number) => setSubgroupSize(value)}
                  options={[2, 3, 4, 5, 6, 7, 8, 9, 10].map((value) => ({
                    value, label: zh ? `子群 ${value}` : `n=${value}`,
                  }))}
                />
              )}
              <Button type="primary" icon={<ThunderboltOutlined />} loading={loading} disabled={!field} onClick={() => void run()} data-testid="spc-run">
                {zh ? "分析" : "Analyze"}
              </Button>
            </Space>
          )}
        />
        <Card size="small" style={{ marginBottom: 16 }} title={zh ? "规格限与判异规则" : "Spec limits & rules"}>
          <Space wrap size="large">
            <Space size={4} align="center">
              <Typography.Text type="secondary">{zh ? "场景规格优先" : "Prefer scene spec"}</Typography.Text>
              <Switch aria-label={zh ? "使用场景规格" : "Use scene spec"} checked={useSceneSpec} onChange={setUseSceneSpec} />
            </Space>
            <InputNumber aria-label="USL" placeholder="USL" style={{ width: 120 }} value={usl ?? null} onChange={(value) => setUsl(value ?? undefined)} />
            <InputNumber aria-label="LSL" placeholder="LSL" style={{ width: 120 }} value={lsl ?? null} onChange={(value) => setLsl(value ?? undefined)} />
            <InputNumber aria-label={zh ? "目标值" : "Target"} placeholder={zh ? "目标值" : "Target"} style={{ width: 120 }} value={target ?? null} onChange={(value) => setTarget(value ?? undefined)} />
            <Select
              aria-label={zh ? "判异场景" : "Scene"} allowClear style={{ minWidth: 160 }}
              placeholder={zh ? "判异场景（联动冻结基线与规格）" : "Scene"} value={sceneId}
              onChange={(value: string | undefined) => { setSceneId(value); setStationId(undefined); }}
              options={scenes.map((item) => ({ value: item.id, label: `${item.name}（${item.code}）` }))}
            />
            <Select
              aria-label={zh ? "判异工位" : "Station"} allowClear style={{ minWidth: 150 }}
              placeholder={zh ? "工位（冻结基线）" : "Station"} value={stationId}
              onChange={setStationId}
              options={stations.filter((item) => !sceneId || item.scene_id === sceneId).map((item) => ({
                value: item.id, label: `${item.name}（${item.code}）`,
              }))}
            />
            <Space size={4} align="center">
              <Typography.Text type="secondary">{zh ? "登记预警" : "Raise alerts"}</Typography.Text>
              <Switch
                aria-label={zh ? "判异登记预警" : "Raise alerts on violations"}
                checked={raiseAlerts} disabled={!canHandle} onChange={setRaiseAlerts}
              />
            </Space>
          </Space>
        </Card>
        {!result ? (
          <Card><Empty description={zh ? "选择来源、过程参数与控制图后点「分析」" : "Pick a source, field and chart, then analyze"} /></Card>
        ) : (
          <>
            <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
              <Col span={4}><Card size="small"><Statistic title={zh ? "样本数" : "Points"} value={result.sample_count} /></Card></Col>
              <Col span={4}><Card size="small"><Statistic title={zh ? "判异点" : "Violations"} value={result.violation_count} valueStyle={result.violation_count > 0 ? { color: "#cf1322" } : undefined} /></Card></Col>
              <Col span={4}><Card size="small"><Statistic title={zh ? "受控率" : "In control"} formatter={() => {
                const chartName = Object.keys(result.charts)[0];
                const rate = result.charts[chartName]?.in_control_rate;
                return rate === null || rate === undefined ? "-" : `${(rate * 100).toFixed(1)}%`;
              }} /></Card></Col>
              <Col span={4}><Card size="small"><Statistic title={zh ? "规格来源" : "Spec source"} formatter={() => {
                const sourceText = { scene_spec: zh ? "场景规格定义" : "Scene spec", manual: zh ? "手工录入" : "Manual", none: zh ? "无" : "None", "scene_spec+manual": zh ? "场景+手工" : "Scene+manual" }[result.spec.source] ?? result.spec.source;
                return sourceText;
              }} /></Card></Col>
              <Col span={8}>
                <Card size="small" title={zh ? "能力指数" : "Capability"} styles={{ body: { padding: "8px 12px" } }}>
                  <Space wrap size={12}>
                    {capabilityEntries.map(([label, value]) => (
                      <Statistic
                        key={label} title={label} precision={2}
                        value={typeof value === "number" ? value : undefined}
                        formatter={typeof value === "number" ? undefined : () => "-"}
                        valueStyle={typeof value === "number" && label.startsWith("C") && value < 1.33 && !label.startsWith("Cr") ? { color: "#cf1322" } : undefined}
                      />
                    ))}
                  </Space>
                </Card>
              </Col>
            </Row>
            {result.notes.length > 0 && (
              /* 诚实设计②：口径脚注（组内 σ 来源、规格来源、无规格限留空） */
              <Typography.Paragraph type="secondary" data-testid="spc-notes" style={{ marginBottom: 12 }}>
                {result.notes.join("；")}。
              </Typography.Paragraph>
            )}
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={15}>
                <Card size="small" title={zh ? "控制图（红点 = 判异）" : "Control chart (red = violation)"} data-testid="spc-chart">
                  {controlOption && <ReactECharts notMerge style={{ height: 340 }} option={controlOption} />}
                </Card>
              </Col>
              <Col xs={24} lg={9}>
                <Card size="small" title={zh ? "直方图（黄色 = 规格带外）" : "Histogram"} data-testid="spc-histogram">
                  {histogramOption && <ReactECharts notMerge style={{ height: 340 }} option={histogramOption} />}
                </Card>
              </Col>
              <Col span={24}>
                <Card size="small" title={zh ? "判异明细" : "Violations"} styles={{ body: { padding: 0 } }} data-testid="spc-violations">
                  <Table
                    rowKey={(row) => `${row.chart}-${row.rule}-${row.index}`}
                    size="small" pagination={{ pageSize: 10 }}
                    dataSource={result.violations}
                    columns={[
                      { title: zh ? "图" : "Chart", dataIndex: "chart", width: 90 },
                      { title: zh ? "规则" : "Rule", dataIndex: "rule", width: 200, render: (value: number) => `${value}. ${RULE_TEXT[value] ?? ""}` },
                      { title: zh ? "点位" : "Point", dataIndex: "index", width: 70 },
                      { title: zh ? "数值" : "Value", dataIndex: "value", width: 100 },
                      { title: zh ? "样本键" : "Sample", dataIndex: "sample_key", width: 140, render: (value: string | null) => value ?? "-" },
                      { title: zh ? "时间" : "Time", dataIndex: "occurred_at", width: 150, render: (value: string | null) => value?.slice(0, 19).replace("T", " ") ?? "-" },
                    ]}
                    locale={{ emptyText: zh ? "没有判异点：过程受控" : "No violations: in control" }}
                  />
                </Card>
              </Col>
            </Row>
            {result.alerts_raised > 0 && (
              <Typography.Paragraph style={{ marginTop: 12 }} data-testid="spc-alerts-raised">
                <Tag color="orange">{zh ? `已登记 ${result.alerts_raised} 条 SPC 判异预警` : `${result.alerts_raised} alert(s) raised`}</Tag>
                {zh ? "可在预警中心按 SPC 判异来源筛选；同一图同一规则在窗口内重复分析只增计数。"
                  : "Filter the alert center by SPC violations; repeated analysis merges into the same alert."}
              </Typography.Paragraph>
            )}
            <Typography.Paragraph type="secondary" style={{ marginTop: 12 }} data-testid="spc-footnote">
              {zh
                ? "口径（诚实设计②）：Cp / Cpk 用组内标准差（子群极差或冻结基线 σ），Pp / Ppk 用整体标准差；组内 σ 无法得到时回退整体 σ 并在上文注明，此时 Cp / Cpk 实际等同于 Pp / Ppk；估计 PPM 按正态近似。缺规格限时能力指数留空。"
                : "Cp/Cpk use within-subgroup sigma; Pp/Ppk use overall sigma; estimated PPM assumes normality. Capability is blank without spec limits."}
            </Typography.Paragraph>
          </>
        )}
      </V2PageFrame>
    </AppLayout>
  );
}
