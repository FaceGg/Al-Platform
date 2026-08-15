import { useEffect, useRef, useState } from "react";
import { Button, Card, Col, Empty, Progress, Row, Select, Space, Spin, Table, Tag, Typography } from "antd";
import { EyeOutlined, ReloadOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";

import apiClient from "../api/client";
import { getQualityWarningSummary, type QualityWarningSummary } from "../api/spotWeldQuality";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Text } = Typography;
const HISTORY_LENGTH = 30;

interface ResourceMetric {
  usage_percent: number;
  total_gb?: number;
  used_gb?: number;
}

interface MonitorData {
  cpu: ResourceMetric;
  memory: ResourceMetric;
  disk: ResourceMetric;
  gpu: ResourceMetric;
}

interface ProjectOption {
  id: string;
  name: string;
}

function toGigaBytes(bytes: number): number {
  return bytes / (1024 * 1024 * 1024);
}

export default function MonitorPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<MonitorData | null>(null);
  const [history, setHistory] = useState<{ cpu: number[]; memory: number[]; disk: number[]; gpu: number[] }>({
    cpu: [], memory: [], disk: [], gpu: [],
  });
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [qualityProjectId, setQualityProjectId] = useState<string>();
  const [qualityWarnings, setQualityWarnings] = useState<QualityWarningSummary | null>(null);
  const [loadingQualityWarnings, setLoadingQualityWarnings] = useState(false);
  const qualityWarningsRequestId = useRef(0);

  const mapBackendResponse = (raw: any): MonitorData => ({
    cpu: { usage_percent: raw.cpu?.percent ?? 0 },
    memory: {
      usage_percent: raw.memory?.percent ?? 0,
      total_gb: raw.memory?.total_bytes ? toGigaBytes(raw.memory.total_bytes) : undefined,
      used_gb: raw.memory?.used_bytes ? toGigaBytes(raw.memory.used_bytes) : undefined,
    },
    disk: {
      usage_percent: raw.disk?.percent ?? 0,
      total_gb: raw.disk?.total ? toGigaBytes(raw.disk.total) : undefined,
      used_gb: raw.disk?.used ? toGigaBytes(raw.disk.used) : undefined,
    },
    gpu: {
      usage_percent: Array.isArray(raw.gpu) && raw.gpu.length > 0 ? raw.gpu[0].gpu_util ?? 0 : 0,
      total_gb: Array.isArray(raw.gpu) && raw.gpu.length > 0 ? (raw.gpu[0].memory_total_mb ?? 0) / 1024 : undefined,
      used_gb: Array.isArray(raw.gpu) && raw.gpu.length > 0 ? (raw.gpu[0].memory_used_mb ?? 0) / 1024 : undefined,
    },
  });

  const fetchData = async () => {
    try {
      const res = await apiClient.get("/monitor/current");
      const mapped = mapBackendResponse(res.data);
      setData(mapped);
      setHistory((prev) => ({
        cpu: [...prev.cpu.slice(-HISTORY_LENGTH + 1), mapped.cpu.usage_percent],
        memory: [...prev.memory.slice(-HISTORY_LENGTH + 1), mapped.memory.usage_percent],
        disk: [...prev.disk.slice(-HISTORY_LENGTH + 1), mapped.disk.usage_percent],
        gpu: [...prev.gpu.slice(-HISTORY_LENGTH + 1), mapped.gpu.usage_percent],
      }));
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const fetchQualityWarnings = async (projectId: string) => {
    const requestId = ++qualityWarningsRequestId.current;
    setLoadingQualityWarnings(true);
    try {
      const warnings = await getQualityWarningSummary(projectId);
      if (qualityWarningsRequestId.current === requestId) {
        setQualityWarnings(warnings);
      }
    } catch {
      if (qualityWarningsRequestId.current === requestId) {
        setQualityWarnings(null);
      }
    } finally {
      if (qualityWarningsRequestId.current === requestId) {
        setLoadingQualityWarnings(false);
      }
    }
  };

  useEffect(() => {
    let active = true;
    apiClient.get("/projects").then((response) => {
      if (!active) return;
      const values = Array.isArray(response.data) ? response.data : response.data?.items;
      setProjects(Array.isArray(values) ? values : []);
    }).catch(() => { if (active) setProjects([]); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    void fetchData();
    const timer = window.setInterval(() => { void fetchData(); }, 3000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!qualityProjectId) {
      qualityWarningsRequestId.current += 1;
      setQualityWarnings(null);
      setLoadingQualityWarnings(false);
      return;
    }
    void fetchQualityWarnings(qualityProjectId);
    return () => { qualityWarningsRequestId.current += 1; };
  }, [qualityProjectId]);

  const svgLineChart = (values: number[], color: string, width = 300, height = 80) => {
    if (values.length < 2) return null;
    const maxVal = Math.max(...values, 5);
    const points = values.map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - (value / (maxVal || 1)) * height;
      return `${x},${y}`;
    });
    const pathD = points.map((point, index) => `${index === 0 ? "M" : "L"}${point}`).join(" ");
    return <svg width={width} height={height} style={{ display: "block" }} aria-hidden="true">
      <path d={pathD} fill="none" stroke={color} strokeWidth="2" />
      {points.map((point, index) => <circle key={index} cx={point.split(",")[0]} cy={point.split(",")[1]} r="2" fill={color} />)}
    </svg>;
  };

  const gaugeColor = (pct: number) => (pct > 80 ? "#d64747" : pct > 60 ? "#b67a1d" : "#247a54");
  const warningColor: Record<string, string> = { critical: "error", warning: "warning", notice: "processing", none: "default" };
  const cards = [
    { key: "cpu", title: t.monitor.cpu, data: data?.cpu },
    { key: "memory", title: t.monitor.memory, data: data?.memory },
    { key: "disk", title: t.monitor.disk, data: data?.disk },
    { key: "gpu", title: t.monitor.gpu, data: data?.gpu },
  ];

  if (loading) {
    return <AppLayout><div style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: 300 }}><Spin size="large" /></div></AppLayout>;
  }

  const warningItems = qualityWarnings?.items || [];
  return <AppLayout>
    <section className="monitor-page page-shell fade-in">
      <div className="page-header page-header--stacked">
        <div className="page-header-copy"><h3 className="page-title">{t.monitor.title}</h3></div>
        <Button icon={<ReloadOutlined />} onClick={() => { void fetchData(); if (qualityProjectId) void fetchQualityWarnings(qualityProjectId); }}>{t.monitor.refresh}</Button>
      </div>
      <Row gutter={[16, 16]}>
        {cards.map((card) => {
          const metric = card.data;
          const percent = metric?.usage_percent ?? 0;
          const values = history[card.key as keyof typeof history];
          return <Col xs={24} sm={12} lg={6} key={card.key}>
            <Card>
              <div style={{ textAlign: "center", padding: "8px 0" }}>
                <Progress type="dashboard" percent={Math.round(percent)} strokeColor={gaugeColor(percent)} size={120} />
                <div style={{ fontWeight: 600, fontSize: 15, marginTop: 8 }}>{card.title}</div>
                {metric?.total_gb != null && <Text type="secondary">{t.monitor.used}: {metric.used_gb?.toFixed(1)} GB / {t.monitor.total}: {metric.total_gb?.toFixed(1)} GB</Text>}
              </div>
              <div style={{ marginTop: 12 }}><Text type="secondary" style={{ fontSize: 11 }}>{t.monitor.usage}</Text>{svgLineChart(values, gaugeColor(percent), 260, 60)}</div>
            </Card>
          </Col>;
        })}
      </Row>
      <section className="monitor-quality-warnings" aria-labelledby="quality-warning-title">
        <div className="monitor-quality-warnings__head">
          <h4 id="quality-warning-title">点焊质量预警</h4>
          <Select aria-label="质量预警项目" placeholder="选择项目" value={qualityProjectId} onChange={setQualityProjectId} options={projects.map((project) => ({ value: project.id, label: project.name }))} style={{ width: "min(320px, 100%)" }} />
        </div>
        {!qualityProjectId ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择项目" /> : loadingQualityWarnings ? <Spin /> : <>
          <Space className="monitor-quality-warnings__counts" size={[6, 6]} wrap>{["critical", "warning", "notice", "none"].map((level) => <Tag key={level} color={warningColor[level]}>{level}: {qualityWarnings?.counts?.[level as keyof QualityWarningSummary["counts"]] || 0}</Tag>)}</Space>
          <Table rowKey={(item) => `${item.run_id}:${item.id}`} size="small" pagination={false} dataSource={warningItems} scroll={{ x: 680 }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无点焊预警" /> }} columns={[
            { title: "样本", dataIndex: "display_id", key: "sample" },
            { title: "告警", dataIndex: "warning_level", key: "warning", render: (level: string) => <Tag color={warningColor[level] || "default"}>{level}</Tag> },
            { title: "缺陷概率", dataIndex: "defect_probability", key: "probability", render: (value: number | null | undefined) => value == null ? "-" : `${(value * 100).toFixed(1)}%` },
            { title: "标签", key: "label", render: (_: unknown, item) => item.current_label || item.automatic_label || "-" },
            { title: "操作", key: "action", width: 120, render: (_: unknown, item) => <Button type="text" icon={<EyeOutlined />} aria-label={`查看样本 ${item.display_id}`} onClick={() => navigate(`/data-annotation?projectId=${encodeURIComponent(qualityProjectId)}&runId=${encodeURIComponent(item.run_id)}&sampleId=${encodeURIComponent(item.id)}`)}>查看样本</Button> },
          ]} />
        </>}
      </section>
    </section>
  </AppLayout>;
}
