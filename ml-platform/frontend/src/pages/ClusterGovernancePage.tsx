import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, Space, Table, Tag, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { App as AntApp } from "antd";
import { formatApiError } from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";
import {
  listQuotaPolicies,
  listReservations,
  listRoutingPolicies,
  listStorageBindings,
  listUsage,
  QuotaPolicy,
  Reservation,
  RoutingPolicy,
  routingPreview,
  RoutingPreview,
  StorageBinding,
  UsageSnapshot,
} from "../api/clusterGovernance";

interface ProjectOption {
  id: string;
  name: string;
}

export default function ClusterGovernancePage() {
  const { t } = useI18n();
  const { message } = AntApp.useApp();
  const gt = (key: string, fallback: string) =>
    (t as unknown as Record<string, Record<string, string>>)?.clusterGovernance?.[key] ?? fallback;

  const [projectId, setProjectId] = useState<string | null>(null);
  const [policies, setPolicies] = useState<RoutingPolicy[]>([]);
  const [bindings, setBindings] = useState<StorageBinding[]>([]);
  const [quotas, setQuotas] = useState<QuotaPolicy[]>([]);
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [usage, setUsage] = useState<UsageSnapshot[]>([]);
  const [staleByCluster, setStaleByCluster] = useState<Record<string, boolean>>({});
  const [preview, setPreview] = useState<RoutingPreview | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const projectRes = await (await import("../api/client")).default.get("/projects");
      const items: ProjectOption[] = projectRes.data?.items ?? [];
      const current = projectId ?? items[0]?.id ?? null;
      setProjectId(current);
      if (!current) return;
      const [pol, bind, quota, reserve, usageData] = await Promise.all([
        listRoutingPolicies(current),
        listStorageBindings(current),
        listQuotaPolicies(),
        listReservations(current),
        listUsage(current),
      ]);
      setPolicies(pol.items);
      setBindings(bind.items);
      setQuotas(quota.items);
      setReservations(reserve.items);
      setUsage(usageData.items);
      setStaleByCluster(usageData.stale_by_cluster ?? {});
    } catch (error) {
      message.error(formatApiError(error, gt("loadFailed", "加载失败")));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const handlePreview = async () => {
    if (!projectId) return;
    try {
      setPreview(await routingPreview(projectId));
    } catch (error) {
      message.error(formatApiError(error, gt("previewFailed", "预演失败")));
    }
  };

  const policyColumns = [
    { title: gt("priority", "优先级"), dataIndex: "priority", key: "priority" },
    {
      title: gt("policy", "策略"),
      dataIndex: "policy_json",
      key: "policy_json",
      render: (value: Record<string, unknown>) => <code>{JSON.stringify(value)}</code>,
    },
    { title: gt("revision", "版本"), dataIndex: "revision", key: "revision" },
  ];

  const bindingColumns = [
    { title: gt("mode", "类型"), dataIndex: "mode", key: "mode", render: (mode: string) => <Tag>{mode}</Tag> },
    {
      title: gt("target", "目标"),
      key: "target",
      render: (_: unknown, row: StorageBinding) => row.pvc_name ?? row.object_prefix ?? "-",
    },
    {
      title: gt("access", "访问"),
      dataIndex: "access",
      key: "access",
      render: (access: string) => <Tag color={access === "read_only" ? "default" : "blue"}>{access}</Tag>,
    },
  ];

  const quotaColumns = [
    { title: gt("scope", "范围"), dataIndex: "scope", key: "scope" },
    { title: gt("revision", "版本"), dataIndex: "revision", key: "revision" },
    {
      title: gt("quota", "配额"),
      dataIndex: "quota_json",
      key: "quota_json",
      render: (value: Record<string, number>) => (
        <Space size={4} wrap>
          {Object.entries(value).map(([key, limit]) => (
            <Tag key={key}>{`${key}=${limit}`}</Tag>
          ))}
        </Space>
      ),
    },
  ];

  const reservationColumns = [
    { title: gt("operation", "操作"), dataIndex: "operation_id", key: "operation_id", ellipsis: true },
    {
      title: gt("state", "状态"),
      dataIndex: "state",
      key: "state",
      render: (state: string) => <Tag color={state === "active" ? "processing" : "default"}>{state}</Tag>,
    },
    {
      title: gt("reserved", "预留量"),
      dataIndex: "reserved_json",
      key: "reserved_json",
      render: (value: Record<string, number>) => JSON.stringify(value),
    },
    { title: gt("releaseReason", "释放原因"), dataIndex: "release_reason", key: "release_reason" },
  ];

  const usageColumns = [
    { title: gt("scope", "范围"), dataIndex: "scope", key: "scope", render: (scope: string) => <Tag>{scope}</Tag> },
    { title: gt("subject", "对象"), dataIndex: "subject", key: "subject" },
    {
      title: gt("metrics", "指标"),
      dataIndex: "metrics_json",
      key: "metrics_json",
      render: (value: Record<string, unknown>) => <code>{JSON.stringify(value)}</code>,
    },
    {
      title: gt("truncated", "截断"),
      dataIndex: "truncated",
      key: "truncated",
      render: (truncated: boolean) => (truncated ? <Tag color="warning">truncated</Tag> : null),
    },
  ];

  const anyStale = Object.values(staleByCluster).some(Boolean);

  return (
    <AppLayout>
      <div style={{ padding: 24, display: "grid", gap: 16 }}>
        <Space>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {gt("title", "集群治理")}
          </Typography.Title>
          <Button icon={<ReloadOutlined />} onClick={load}>
            {gt("refresh", "刷新")}
          </Button>
          <Button type="primary" onClick={handlePreview}>
            {gt("preview", "路由预演")}
          </Button>
        </Space>
        {anyStale ? (
          <Alert type="warning" showIcon message={gt("staleWarning", "部分集群用量快照已过期(采集失败或断源)")} />
        ) : null}
        {preview ? (
          <Card size="small" title={gt("previewTitle", "路由预演")}>
            <p>
              {gt("selected", "选中")}: {preview.selected_cluster_id ?? "-"} · {gt("reason", "原因")}: {preview.reason}
            </p>
            <Table
              rowKey="cluster_id"
              size="small"
              pagination={false}
              columns={[
                { title: gt("cluster", "集群"), dataIndex: "name", key: "name" },
                {
                  title: gt("eligible", "是否可选"),
                  key: "excluded",
                  render: (_: unknown, row: { excluded: boolean; reason: string | null }) =>
                    row.excluded ? <Tag color="error">{row.reason}</Tag> : <Tag color="success">ok</Tag>,
                },
              ]}
              dataSource={preview.candidates}
            />
          </Card>
        ) : null}
        <Card size="small" title={gt("policiesTitle", "路由策略")}>
          <Table rowKey="id" size="small" loading={loading} columns={policyColumns as never} dataSource={policies} pagination={false} />
        </Card>
        <Card size="small" title={gt("bindingsTitle", "存储绑定")}>
          <Table rowKey="id" size="small" loading={loading} columns={bindingColumns as never} dataSource={bindings} pagination={false} />
        </Card>
        <Card size="small" title={gt("quotasTitle", "资源配额")}>
          <Table rowKey="id" size="small" loading={loading} columns={quotaColumns as never} dataSource={quotas} pagination={false} />
        </Card>
        <Card size="small" title={gt("reservationsTitle", "活跃预留")}>
          <Table rowKey="id" size="small" loading={loading} columns={reservationColumns as never} dataSource={reservations} pagination={false} />
        </Card>
        <Card size="small" title={gt("usageTitle", "用量快照")}>
          <Table rowKey="id" size="small" loading={loading} columns={usageColumns as never} dataSource={usage} pagination={false} />
        </Card>
      </div>
    </AppLayout>
  );
}
