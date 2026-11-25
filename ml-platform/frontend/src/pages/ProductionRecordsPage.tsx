import { useCallback, useEffect, useState } from "react";
import { App as AntApp, Button, Card, Col, Empty, Input, Row, Select, Space, Statistic, Table, Tag } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import apiClient, { formatApiError } from "../api/client";
import { listQualityScenes, listQualityStations } from "../api/qualityDomain";
import type { QualityScene, QualityStation } from "../api/qualityDomain";
import { useI18n } from "../i18n";
import { formatLocalTime } from "../utils/time";

/** 质量管理 · 监控 / 生产记录（B1-16，P3）：推理结果明细查询。 */

interface InferenceResultRow {
  id: string;
  request_id: string;
  sample_key: string | null;
  channel: string;
  station_id: string | null;
  scene_id: string | null;
  condition_value: string | null;
  predicted_label: string | null;
  predicted_value: number | null;
  probability: number | null;
  anomaly_score: number | null;
  is_anomaly: boolean | null;
  threshold: number | null;
  batch_no: string | null;
  shift: string | null;
  product_code: string | null;
  occurred_at: string | null;
  snapshot_uri: string | null;
}

interface SummaryBody {
  total: number;
  ok_count: number;
  anomaly_count: number;
}

export default function ProductionRecordsPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [scenes, setScenes] = useState<QualityScene[]>([]);
  const [stations, setStations] = useState<QualityStation[]>([]);
  const [rows, setRows] = useState<InferenceResultRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState<SummaryBody | null>(null);
  const [filters, setFilters] = useState<{
    sample_key?: string;
    batch_no?: string;
    scene_id?: string;
    station_id?: string;
    is_anomaly?: string;
  }>({});

  useEffect(() => {
    apiClient.get("/projects").then((res) => {
      const items = (res.data?.items || []).map((p: { id: string; name: string }) => ({ id: p.id, name: p.name }));
      setProjects(items);
      if (items.length > 0) setProjectId((current) => current ?? items[0].id);
    }).catch(() => setProjects([]));
  }, []);

  useEffect(() => {
    if (!projectId) { setScenes([]); setStations([]); return; }
    listQualityScenes(projectId).then(setScenes).catch(() => setScenes([]));
    listQualityStations(projectId).then(setStations).catch(() => setStations([]));
  }, [projectId]);

  const load = useCallback(() => {
    if (!projectId) { setRows([]); setTotal(0); return; }
    setLoading(true);
    const params: Record<string, unknown> = { page, page_size: pageSize };
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== "") params[key] = value;
    }
    apiClient.get(`/projects/${projectId}/inference-results`, { params })
      .then((res) => {
        setRows(Array.isArray(res.data?.items) ? res.data.items : []);
        setTotal(Number(res.data?.total || 0));
      })
      .catch((e) => message.error(formatApiError(e, zh ? "查询失败" : "Query failed")))
      .finally(() => setLoading(false));
    apiClient.get(`/projects/${projectId}/inference-results/summary`)
      .then((res) => setSummary(res.data))
      .catch(() => setSummary(null));
  }, [projectId, page, pageSize, filters, zh, message]);

  useEffect(() => { load(); }, [load]);

  const stationName = (id: string | null) => {
    if (!id) return "-";
    const station = stations.find((item) => item.id === id);
    return station ? `${station.name}（${station.code}）` : "-";
  };

  const columns = [
    {
      title: zh ? "时间" : "Time", dataIndex: "occurred_at", key: "occurred_at", width: 170,
      render: (value: string | null) => (value ? formatLocalTime(value) : "-"),
    },
    {
      title: zh ? "样本键" : "Sample key", dataIndex: "sample_key", key: "sample_key",
      render: (value: string | null) => value || "-",
    },
    { title: zh ? "批次" : "Batch", dataIndex: "batch_no", key: "batch_no", render: (value: string | null) => value || "-" },
    { title: zh ? "工位" : "Station", key: "station", render: (_: unknown, row: InferenceResultRow) => stationName(row.station_id) },
    { title: zh ? "工况" : "Condition", dataIndex: "condition_value", key: "condition_value", render: (value: string | null) => value || "-" },
    {
      title: zh ? "结果" : "Result", key: "result",
      render: (_: unknown, row: InferenceResultRow) => {
        if (row.is_anomaly === true) return <Tag color="error">{zh ? "异常" : "Anomaly"}</Tag>;
        if (row.is_anomaly === false) return <Tag color="success">{zh ? "正常" : "OK"}</Tag>;
        if (row.predicted_label != null) return <Tag>{row.predicted_label}</Tag>;
        if (row.predicted_value != null) return <Tag>{row.predicted_value}</Tag>;
        return "-";
      },
    },
    {
      title: zh ? "分数/阈值" : "Score / Threshold", key: "score",
      render: (_: unknown, row: InferenceResultRow) => {
        if (row.anomaly_score == null && row.probability == null) return "-";
        const score = row.anomaly_score ?? row.probability;
        const threshold = row.threshold != null ? ` / ${row.threshold}` : "";
        return `${score}${threshold}`;
      },
    },
    {
      title: zh ? "通道" : "Channel", dataIndex: "channel", key: "channel", width: 90,
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: zh ? "快照" : "Snapshot", key: "snapshot", width: 70,
      render: (_: unknown, row: InferenceResultRow) => (row.snapshot_uri ? <Tag color="blue">{zh ? "有" : "Yes"}</Tag> : "-"),
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_production_records" testId="v2-production-records">
        <PageHeading
          section="quality"
          navKey="quality_production_records"
          desc={zh ? "逐样本推理结果明细：按样本键、批次、工位查询；演示数据默认不显示。" : "Per-sample inference results by sample key, batch and station; demo data hidden by default."}
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
              <Input
                aria-label={zh ? "样本键" : "Sample key"}
                allowClear
                style={{ width: 150 }}
                placeholder={zh ? "样本键" : "Sample key"}
                onPressEnter={(event) => { setFilters((f) => ({ ...f, sample_key: (event.target as HTMLInputElement).value })); setPage(1); }}
              />
              <Input
                aria-label={zh ? "批次" : "Batch"}
                allowClear
                style={{ width: 130 }}
                placeholder={zh ? "批次" : "Batch"}
                onPressEnter={(event) => { setFilters((f) => ({ ...f, batch_no: (event.target as HTMLInputElement).value })); setPage(1); }}
              />
              <Select
                aria-label={zh ? "场景筛选" : "Scene filter"}
                allowClear
                style={{ minWidth: 150 }}
                placeholder={zh ? "场景" : "Scene"}
                value={filters.scene_id}
                onChange={(value: string | undefined) => { setFilters((f) => ({ ...f, scene_id: value, station_id: undefined })); setPage(1); }}
                options={scenes.map((s) => ({ value: s.id, label: `${s.name}（${s.code}）` }))}
              />
              <Select
                aria-label={zh ? "工位筛选" : "Station filter"}
                allowClear
                style={{ minWidth: 150 }}
                placeholder={zh ? "工位" : "Station"}
                value={filters.station_id}
                onChange={(value: string | undefined) => { setFilters((f) => ({ ...f, station_id: value })); setPage(1); }}
                options={stations.filter((s) => !filters.scene_id || s.scene_id === filters.scene_id).map((s) => ({ value: s.id, label: `${s.name}（${s.code}）` }))}
              />
              <Select
                aria-label={zh ? "异常筛选" : "Anomaly filter"}
                allowClear
                style={{ width: 110 }}
                placeholder={zh ? "异常" : "Anomaly"}
                value={filters.is_anomaly}
                onChange={(value: string | undefined) => { setFilters((f) => ({ ...f, is_anomaly: value })); setPage(1); }}
                options={[
                  { value: "true", label: zh ? "仅异常" : "Anomalies" },
                  { value: "false", label: zh ? "仅正常" : "OK only" },
                ]}
              />
              <Button icon={<ReloadOutlined />} onClick={load}>{zh ? "刷新" : "Refresh"}</Button>
            </Space>
          }
        />
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Card size="small"><Statistic title={zh ? "24h 推理总数" : "Inferences (24h)"} value={summary?.total ?? 0} /></Card>
          </Col>
          <Col span={8}>
            <Card size="small"><Statistic title={zh ? "正常" : "OK"} value={summary?.ok_count ?? 0} valueStyle={{ color: "#3f8600" }} /></Card>
          </Col>
          <Col span={8}>
            <Card size="small"><Statistic title={zh ? "异常" : "Anomalies"} value={summary?.anomaly_count ?? 0} valueStyle={{ color: "#cf1322" }} /></Card>
          </Col>
        </Row>
        <Card>
          <Table
            rowKey="id"
            loading={loading}
            columns={columns}
            dataSource={rows}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              onChange: (nextPage, nextSize) => { setPage(nextPage); setPageSize(nextSize); },
            }}
            locale={{ emptyText: <Empty description={zh ? "暂无记录：带上下文的推理请求落库后在此可查（演示通道数据默认隐藏）" : "No records yet"} /> }}
          />
        </Card>
      </V2PageFrame>
    </AppLayout>
  );
}
