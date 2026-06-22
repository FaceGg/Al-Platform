import { useEffect, useState } from "react";
import { Card, Table, Tag, Typography } from "antd";
import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";
import dayjs from "dayjs";

const { Text } = Typography;

const statusColors: Record<string, string> = {
  pending: "default", running: "blue", completed: "green", failed: "red",
  queued: "default", processing: "blue", done: "green", error: "red",
};

export default function TrainingJobsPage() {
  const { t } = useI18n();
  const [jobs, setJobs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    apiClient.get("/training/jobs")
      .then((res) => setJobs(res.data.items || res.data || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  const columns = [
    {
      title: t.knowledge.name, dataIndex: "name", key: "name", ellipsis: true,
      render: (text: string) => text || "-",
    },
    {
      title: t.training.operator, dataIndex: "operator", key: "operator",
      render: (v: string) => v ? <Tag>{v}</Tag> : "-",
    },
    {
      title: t.training.status, dataIndex: "status", key: "status",
      render: (v: string) => (
        <Tag color={statusColors[v] || "default"}>{(v || "pending").toUpperCase()}</Tag>
      ),
    },
    {
      title: t.training.metrics, dataIndex: "metrics", key: "metrics",
      render: (m: any) => {
        if (!m) return "-";
        const entries = Object.entries(m).slice(0, 3);
        return (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {entries.map(([k, v]) => (
              <Tag key={k}>{k}: {typeof v === "number" ? Number(v).toFixed(4) : String(v)}</Tag>
            ))}
          </div>
        );
      },
    },
    {
      title: t.training.started, dataIndex: "created_at", key: "created_at", width: 160,
      render: (v: string) => v ? dayjs(v).format("YYYY-MM-DD HH:mm") : "-",
    },
    {
      title: t.training.params, dataIndex: "params", key: "params", ellipsis: true,
      render: (p: any) => {
        if (!p) return "-";
        return <Text ellipsis style={{ maxWidth: 200 }}>{JSON.stringify(p)}</Text>;
      },
    },
  ];

  return (
    <AppLayout>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <h3>{t.training.jobs}</h3>
        <Text type="secondary">{t.monitor.refresh}: 5s</Text>
      </div>
      <Card>
        <Table
          rowKey="id"
          dataSource={jobs}
          columns={columns}
          loading={loading}
          pagination={{ pageSize: 15 }}
          locale={{ emptyText: t.common.loading }}
        />
      </Card>
    </AppLayout>
  );
}
