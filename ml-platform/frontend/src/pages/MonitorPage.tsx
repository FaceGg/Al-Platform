import { useEffect, useState } from "react";
import { Card, Row, Col, Progress, Button, Typography, Spin } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Text } = Typography;
const HISTORY_LENGTH = 30;

interface ResourceMetric {
  usage_percent: number; total_gb?: number; used_gb?: number;
}

interface MonitorData {
  cpu: ResourceMetric; memory: ResourceMetric; disk: ResourceMetric; gpu: ResourceMetric;
}

function toGigaBytes(bytes: number): number {
  return bytes / (1024 * 1024 * 1024);
}

export default function MonitorPage() {
  const { t } = useI18n();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<MonitorData | null>(null);
  const [history, setHistory] = useState<{ cpu: number[]; memory: number[]; disk: number[]; gpu: number[] }>({
    cpu: [], memory: [], disk: [], gpu: [],
  });

  const mapBackendResponse = (raw: any): MonitorData => ({
    cpu: {
      usage_percent: raw.cpu?.percent ?? 0,
      total_gb: undefined,
      used_gb: undefined,
    },
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
      usage_percent: (Array.isArray(raw.gpu) && raw.gpu.length > 0) ? (raw.gpu[0].gpu_util ?? 0) : 0,
      total_gb: (Array.isArray(raw.gpu) && raw.gpu.length > 0) ? (raw.gpu[0].memory_total_mb ?? 0) / 1024 : undefined,
      used_gb: (Array.isArray(raw.gpu) && raw.gpu.length > 0) ? (raw.gpu[0].memory_used_mb ?? 0) / 1024 : undefined,
    },
  });

  const fetchData = async () => {
    try {
      const res = await apiClient.get("/monitor/current");
      const mapped = mapBackendResponse(res.data);
      setData(mapped);
      setHistory((prev) => ({
        cpu: [...prev.cpu.slice(-HISTORY_LENGTH + 1), mapped.cpu?.usage_percent ?? 0],
        memory: [...prev.memory.slice(-HISTORY_LENGTH + 1), mapped.memory?.usage_percent ?? 0],
        disk: [...prev.disk.slice(-HISTORY_LENGTH + 1), mapped.disk?.usage_percent ?? 0],
        gpu: [...prev.gpu.slice(-HISTORY_LENGTH + 1), mapped.gpu?.usage_percent ?? 0],
      }));
      setLoading(false);
    } catch { /* silently ignore */ }
  };

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 3000);
    return () => clearInterval(timer);
  }, []);

  const svgLineChart = (values: number[], color: string, width = 300, height = 80) => {
    if (values.length < 2) return null;
    const maxVal = Math.max(...values, 5);
    const minVal = 0;
    const points = values.map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - ((v - minVal) / (maxVal - minVal || 1)) * height;
      return `${x},${y}`;
    });
    const pathD = points.map((p, i) => (i === 0 ? "M" : "L") + p).join(" ");
    return (
      <svg width={width} height={height} style={{ display: "block" }}>
        <path d={pathD} fill="none" stroke={color} strokeWidth="2" />
        {points.map((p, i) => (
          <circle key={i} cx={p.split(",")[0]} cy={p.split(",")[1]} r="2" fill={color} />
        ))}
      </svg>
    );
  };

  const gaugeColor = (pct: number) => (pct > 80 ? "#ff4d4f" : pct > 60 ? "#faad14" : "#52c41a");

  const cards = [
    { key: "cpu", title: t.monitor.cpu, data: data?.cpu },
    { key: "memory", title: t.monitor.memory, data: data?.memory },
    { key: "disk", title: t.monitor.disk, data: data?.disk },
    { key: "gpu", title: t.monitor.gpu, data: data?.gpu },
  ];

  if (loading) {
    return <AppLayout><div style={{display:'flex',justifyContent:'center',alignItems:'center',minHeight:300}}><Spin size="large" /></div></AppLayout>;
  }

  return (
    <AppLayout>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <h3>{t.monitor.title}</h3>
        <Button icon={<ReloadOutlined />} onClick={fetchData}>{t.monitor.refresh}</Button>
      </div>
      <Row gutter={[16, 16]}>
        {cards.map((card) => {
          const d = card.data;
          const pct = d?.usage_percent ?? 0;
          const hist = history[card.key as keyof typeof history];
          return (
            <Col xs={24} sm={12} lg={6} key={card.key}>
              <Card>
                <div style={{ textAlign: "center", padding: "8px 0" }}>
                  <div style={{ position: "relative", display: "inline-block" }}>
                    <Progress
                      type="dashboard"
                      percent={Math.round(pct)}
                      strokeColor={gaugeColor(pct)}
                      size={120}
                    />
                  </div>
                  <div style={{ fontWeight: 600, fontSize: 15, marginTop: 8 }}>{card.title}</div>
                  {d?.total_gb != null && (
                    <Text type="secondary">
                      {t.monitor.used}: {d.used_gb?.toFixed(1)} GB / {t.monitor.total}: {d.total_gb?.toFixed(1)} GB
                    </Text>
                  )}
                </div>
                <div style={{ marginTop: 12 }}>
                  <Text type="secondary" style={{ fontSize: 11 }}>{t.monitor.usage}</Text>
                  {svgLineChart(hist, gaugeColor(pct), 260, 60)}
                </div>
              </Card>
            </Col>
          );
        })}
      </Row>
    </AppLayout>
  );
}
