import { useEffect, useState, useRef } from "react";
import { Card, Row, Col, Progress, Button, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Text, Title } = Typography;
const HISTORY_LENGTH = 30;

interface ResourceMetric {
  usage_percent: number; total_gb?: number; used_gb?: number;
}

interface MonitorData {
  cpu: ResourceMetric; memory: ResourceMetric; disk: ResourceMetric; gpu: ResourceMetric;
}

export default function MonitorPage() {
  const { t } = useI18n();
  const [data, setData] = useState<MonitorData | null>(null);
  const [history, setHistory] = useState<{ cpu: number[]; memory: number[]; disk: number[]; gpu: number[] }>({
    cpu: [], memory: [], disk: [], gpu: [],
  });

  const fetchData = async () => {
    try {
      const res = await apiClient.get("/monitor/current");
      const d: MonitorData = res.data;
      setData(d);
      setHistory((prev) => ({
        cpu: [...prev.cpu.slice(-HISTORY_LENGTH + 1), d.cpu?.usage_percent ?? 0],
        memory: [...prev.memory.slice(-HISTORY_LENGTH + 1), d.memory?.usage_percent ?? 0],
        disk: [...prev.disk.slice(-HISTORY_LENGTH + 1), d.disk?.usage_percent ?? 0],
        gpu: [...prev.gpu.slice(-HISTORY_LENGTH + 1), d.gpu?.usage_percent ?? 0],
      }));
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
                <div style={{ textAlign: "center" }}>
                  <Progress
                    type="dashboard"
                    percent={Math.round(pct)}
                    strokeColor={gaugeColor(pct)}
                    size={120}
                  />
                  <Title level={5} style={{ marginTop: 8 }}>{card.title}</Title>
                  {d?.total_gb != null && (
                    <Text type="secondary">
                      {t.monitor.used}: {d.used_gb?.toFixed(1)} GB / {t.monitor.total}: {d.total_gb?.toFixed(1)} GB
                    </Text>
                  )}
                </div>
                <div style={{ marginTop: 12 }}>
                  <Text type="secondary" style={{ fontSize: 11 }}>{t.monitor.usage} ({t.automl?.score || "history"})</Text>
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
