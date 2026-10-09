import { useCallback, useEffect, useState } from "react";
import { Button, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography } from "antd";
import { CaretRightOutlined, ReloadOutlined, StopOutlined } from "@ant-design/icons";
import { App as AntApp } from "antd";
import apiClient, { formatApiError } from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";
import {
  ContainerImage,
  listImages,
  listNotebooks,
  NotebookSession,
  openNotebook,
  reconcileNotebook,
  startNotebook,
  stopNotebook,
} from "../api/notebooks";

const TERMINAL_STATUSES = ["stopped", "failed", "terminated"];

const STATUS_COLORS: Record<string, string> = {
  starting: "processing",
  running: "success",
  stopping: "processing",
  stopped: "default",
  failed: "error",
  terminated: "default",
};

interface ClusterOption {
  id: string;
  name: string;
}

export default function NotebookPage() {
  const { t } = useI18n();
  const { message } = AntApp.useApp();
  const nt = (key: string, fallback: string) =>
    (t as unknown as Record<string, Record<string, string>>)?.notebooks?.[key] ?? fallback;

  const [sessions, setSessions] = useState<NotebookSession[]>([]);
  const [images, setImages] = useState<ContainerImage[]>([]);
  const [clusters, setClusters] = useState<ClusterOption[]>([]);
  const [namespaces, setNamespaces] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [startOpen, setStartOpen] = useState(false);
  const [form] = Form.useForm();

  const handleClusterChange = useCallback(async (clusterId: string) => {
    setNamespaces([]);
    if (!clusterId) return;
    try {
      const res = await apiClient.get(`/kubernetes/clusters/${clusterId}/namespaces`);
      const items: string[] = res.data?.items ?? [];
      setNamespaces(items);
      form.setFieldValue("namespace", items.includes("w14-demo") ? "w14-demo" : (items[0] ?? undefined));
    } catch {
      setNamespaces([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nb, imgs] = await Promise.all([listNotebooks(), listImages()]);
      setSessions(nb.items);
      setImages(imgs.items);
      const clusterRes = await apiClient.get("/kubernetes/clusters");
      setClusters(
        ((clusterRes.data?.items ?? []) as ClusterOption[]).map((cluster) => ({
          id: cluster.id,
          name: cluster.name,
        })),
      );
    } catch (error) {
      message.error(formatApiError(error, nt("loadFailed", "加载失败")));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleStart = async () => {
    try {
      const values = await form.validateFields();
      await startNotebook({
        cluster_id: values.cluster_id,
        namespace: values.namespace,
        image_ref: values.image_ref,
        idle_timeout_seconds: values.idle_timeout_seconds ?? 3600,
        resources: { cpu_cores: 1, memory_gb: 1 },
      });
      message.success(nt("startOk", "会话已启动"));
      setStartOpen(false);
      await load();
    } catch (error) {
      message.error(formatApiError(error, nt("startFailed", "启动失败")));
    }
  };

  const handleStop = async (session: NotebookSession) => {
    try {
      await stopNotebook(session.id);
      message.success(nt("stopOk", "已停止"));
      await load();
    } catch (error) {
      message.error(formatApiError(error, nt("stopFailed", "停止失败")));
    }
  };

  const handleOpen = async (session: NotebookSession) => {
    try {
      const access = await openNotebook(session.id);
      window.open(`/api/notebooks/${session.id}/proxy/?token=${access.token}`, "_blank");
      await load();
    } catch (error) {
      message.error(formatApiError(error, nt("openFailed", "打开失败")));
    }
  };

  const selectableImages = images.filter((image) => image.scan_status !== "failed");
  const columns = [
    { title: nt("jobName", "会话"), dataIndex: "job_name", key: "job_name" },
    {
      title: nt("status", "状态"),
      dataIndex: "status",
      key: "status",
      render: (status: string) => <Tag color={STATUS_COLORS[status] ?? "default"}>{status}</Tag>,
    },
    { title: nt("image", "镜像"), dataIndex: "image_ref", key: "image_ref", ellipsis: true },
    { title: nt("namespace", "命名空间"), dataIndex: "namespace", key: "namespace" },
    {
      title: nt("idle", "空闲回收(秒)"),
      dataIndex: "idle_timeout_seconds",
      key: "idle_timeout_seconds",
    },
    {
      title: nt("actions", "操作"),
      key: "actions",
      render: (_: unknown, session: NotebookSession) => {
        const terminal = TERMINAL_STATUSES.includes(session.status);
        return (
          <Space>
            <Button
              size="small"
              icon={<CaretRightOutlined />}
              disabled={session.status !== "running"}
              onClick={() => handleOpen(session)}
            >
              {nt("open", "打开")}
            </Button>
            <Button size="small" danger icon={<StopOutlined />} disabled={terminal} onClick={() => handleStop(session)}>
              {nt("stop", "停止")}
            </Button>
          </Space>
        );
      },
    },
  ];

  return (
    <AppLayout>
      <div style={{ padding: 24 }}>
        <Space style={{ marginBottom: 16 }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {nt("title", "Notebook 会话")}
          </Typography.Title>
          <Button icon={<ReloadOutlined />} onClick={load}>
            {nt("refresh", "刷新")}
          </Button>
          <Button type="primary" onClick={() => setStartOpen(true)}>
            {nt("start", "启动会话")}
          </Button>
        </Space>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns as never}
          dataSource={sessions}
          locale={{ emptyText: nt("empty", "暂无会话") }}
          pagination={{ pageSize: 50, showSizeChanger: false }}
        />
        <Modal
          title={nt("start", "启动会话")}
          open={startOpen}
          onOk={handleStart}
          onCancel={() => setStartOpen(false)}
          okText={nt("startOkButton", "启动")}
          cancelText={nt("cancel", "取消")}
        >
          <Form form={form} layout="vertical">
            <Form.Item name="cluster_id" label={nt("cluster", "集群")} rules={[{ required: true }]}>
              <Select
                options={clusters.map((cluster) => ({ value: cluster.id, label: cluster.name }))}
                showSearch
                optionFilterProp="label"
                placeholder={nt("cluster", "集群")}
                onChange={handleClusterChange}
              />
            </Form.Item>
            <Form.Item name="namespace" label={nt("namespace", "命名空间")} rules={[{ required: true }]}>
              <Select
                options={namespaces.map((name) => ({ value: name, label: name }))}
                showSearch
                optionFilterProp="label"
                placeholder={nt("namespace", "命名空间")}
              />
            </Form.Item>
            <Form.Item name="image_ref" label={nt("image", "镜像(仅目录内且扫描通过)")} rules={[{ required: true }]}>
              <Select
                options={selectableImages.map((image) => ({
                  value: `${image.registry}/${image.repository}@${image.digest}`,
                  label: `${image.registry}/${image.repository}@${image.digest.slice(0, 19)}…`,
                }))}
                showSearch
                placeholder={nt("image", "镜像")}
              />
            </Form.Item>
            <Form.Item
              name="idle_timeout_seconds"
              label={nt("idle", "空闲回收(秒)")}
              initialValue={3600}
              rules={[{ required: true }]}
            >
              <Input type="number" min={60} max={86400} />
            </Form.Item>
          </Form>
        </Modal>
      </div>
    </AppLayout>
  );
}
