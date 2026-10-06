import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { ClusterOutlined, ReloadOutlined } from "@ant-design/icons";
import { App as AntApp } from "antd";
import apiClient, { formatApiError } from "../api/client";
import AppLayout from "../components/AppLayout";
import { parseBackendTime } from "../utils/time";
import { useI18n } from "../i18n";
import {
  ClusterInfo,
  createCluster,
  createResourceGroup,
  deleteCluster,
  ensureNamespace,
  listClusterNamespaces,
  listClusterNodes,
  listClusters,
  listResourceGroups,
  NodeCapability,
  NamespaceInfo,
  ResourceGroupInfo,
  runConnectivityCheck,
} from "../api/kubernetes";

const STATUS_COLORS: Record<string, string> = {
  pending: "default",
  active: "success",
  connectivity_failed: "error",
  disabled: "warning",
};

interface ProjectOption {
  id: string;
  name: string;
}

export default function KubernetesPage() {
  const { t } = useI18n();
  const { message } = AntApp.useApp();
  const kt = (key: string, fallback: string) =>
    (t as unknown as Record<string, Record<string, string>>)?.kubernetes?.[key] ?? fallback;

  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [clusters, setClusters] = useState<ClusterInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [checkingId, setCheckingId] = useState<string | null>(null);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [form] = Form.useForm();
  const [nodesTarget, setNodesTarget] = useState<ClusterInfo | null>(null);
  const [nodes, setNodes] = useState<NodeCapability[] | null>(null);
  const [nsTarget, setNsTarget] = useState<ClusterInfo | null>(null);
  const [liveNamespaces, setLiveNamespaces] = useState<string[] | null>(null);
  const [nsForm] = Form.useForm();
  const [rgTarget, setRgTarget] = useState<ClusterInfo | null>(null);
  const [resourceGroups, setResourceGroups] = useState<ResourceGroupInfo[] | null>(null);
  const [rgForm] = Form.useForm();

  const loadProjects = useCallback(async () => {
    try {
      const res = await apiClient.get("/projects");
      const items: ProjectOption[] = res.data?.items ?? [];
      setProjects(items);
      setProjectId((current) => current ?? items[0]?.id ?? null);
    } catch (error) {
      message.error(formatApiError(error, kt("loadFailed", "加载失败")));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadClusters = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listClusters();
      setClusters(data.items);
    } catch (error) {
      message.error(formatApiError(error, kt("loadFailed", "加载失败")));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadProjects();
    loadClusters();
  }, [loadProjects, loadClusters]);

  const visibleClusters = projectId
    ? clusters.filter((cluster) => cluster.project_id === projectId)
    : clusters;

  const handleCheck = async (cluster: ClusterInfo) => {
    setCheckingId(cluster.id);
    try {
      const result = await runConnectivityCheck(cluster.id);
      if (result.check_status === "ok") {
        message.success(`${kt("checkOk", "连通性正常")} · ${result.kubernetes_version ?? ""} · ${result.latency_ms}ms`);
      } else {
        message.error(`${result.error_code ?? "KUBERNETES_CONNECTIVITY_FAILED"} · ${result.latency_ms}ms`);
      }
      await loadClusters();
    } catch (error) {
      message.error(formatApiError(error, kt("checkFailed", "连通性检查失败")));
    } finally {
      setCheckingId(null);
    }
  };

  const handleRegister = async () => {
    try {
      const values = await form.validateFields();
      await createCluster({
        project_id: projectId ?? "",
        name: values.name,
        display_name: values.display_name ?? "",
        api_server_url: values.api_server_url,
        secret_ref: values.secret_ref,
        insecure_tls: values.insecure_tls ?? false,
        provider: values.provider ?? "generic",
        default_namespace: values.default_namespace || null,
      });
      message.success(kt("registerOk", "集群已登记"));
      setRegisterOpen(false);
      form.resetFields();
      await loadClusters();
    } catch (error) {
      message.error(formatApiError(error, kt("registerFailed", "登记失败")));
    }
  };

  const handleDelete = async (cluster: ClusterInfo) => {
    try {
      await deleteCluster(cluster.id);
      message.success(kt("deleteOk", "集群已下线"));
      await loadClusters();
    } catch (error) {
      message.error(formatApiError(error, kt("deleteFailed", "下线失败")));
    }
  };

  const openNodes = async (cluster: ClusterInfo) => {
    setNodesTarget(cluster);
    setNodes(null);
    try {
      const data = await listClusterNodes(cluster.id);
      setNodes(data.items);
    } catch (error) {
      message.error(formatApiError(error, kt("loadFailed", "加载失败")));
      setNodes([]);
    }
  };

  const openNamespaces = async (cluster: ClusterInfo) => {
    setNsTarget(cluster);
    setLiveNamespaces(null);
    try {
      const data = await listClusterNamespaces(cluster.id);
      setLiveNamespaces(data.items);
    } catch (error) {
      message.error(formatApiError(error, kt("loadFailed", "加载失败")));
      setLiveNamespaces([]);
    }
  };

  const handleEnsureNamespace = async () => {
    if (!nsTarget) return;
    try {
      const values = await nsForm.validateFields();
      const quota: Record<string, number> = {};
      if (values.cpuCores) quota.cpu_cores = Number(values.cpuCores);
      if (values.memoryMb) quota.memory_mb = Number(values.memoryMb);
      await ensureNamespace(nsTarget.id, values.namespaceName, Object.keys(quota).length ? quota : null);
      message.success(kt("namespaceOk", "命名空间已就绪"));
      nsForm.resetFields();
      const data = await listClusterNamespaces(nsTarget.id);
      setLiveNamespaces(data.items);
    } catch (error) {
      message.error(formatApiError(error, kt("namespaceFailed", "命名空间操作失败")));
    }
  };

  const openResourceGroups = async (cluster: ClusterInfo) => {
    setRgTarget(cluster);
    setResourceGroups(null);
    try {
      const data = await listResourceGroups(cluster.id);
      setResourceGroups(data.items);
    } catch (error) {
      message.error(formatApiError(error, kt("loadFailed", "加载失败")));
      setResourceGroups([]);
    }
  };

  const handleCreateResourceGroup = async () => {
    if (!rgTarget) return;
    try {
      const values = await rgForm.validateFields();
      const quota: Record<string, number> = {};
      if (values.cpuCores) quota.cpu_cores = Number(values.cpuCores);
      if (values.memoryMb) quota.memory_mb = Number(values.memoryMb);
      await createResourceGroup({
        cluster_id: rgTarget.id,
        name: values.groupName,
        description: values.description ?? "",
        quota_json: quota,
      });
      message.success(kt("rgOk", "资源组已登记"));
      rgForm.resetFields();
      const data = await listResourceGroups(rgTarget.id);
      setResourceGroups(data.items);
    } catch (error) {
      message.error(formatApiError(error, kt("rgFailed", "资源组操作失败")));
    }
  };

  const columns = [
    { title: kt("cluster", "集群"), dataIndex: "name", key: "name", render: (_: unknown, row: ClusterInfo) => (
      <Space direction="vertical" size={0}>
        <Typography.Text strong>{row.display_name || row.name}</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{row.api_server_url}</Typography.Text>
      </Space>
    ) },
    { title: kt("provider", "类型"), dataIndex: "provider", key: "provider", width: 90 },
    { title: kt("status", "状态"), dataIndex: "status", key: "status", width: 140, render: (_: unknown, row: ClusterInfo) => (
      <Space direction="vertical" size={0}>
        <Tag color={STATUS_COLORS[row.status] ?? "default"}>{row.status}</Tag>
        {row.stale && <Tag color="orange">{kt("stale", "检查结果已过期")}</Tag>}
      </Space>
    ) },
    { title: kt("version", "版本"), dataIndex: "kubernetes_version", key: "version", width: 110, render: (v: string | null) => v ?? "-" },
    { title: kt("lastCheck", "最近检查"), key: "lastCheck", width: 180, render: (_: unknown, row: ClusterInfo) => (
      <Space direction="vertical" size={0}>
        <Typography.Text style={{ fontSize: 12 }}>
          {row.last_checked_at ? (parseBackendTime(row.last_checked_at)?.toLocaleString() ?? row.last_checked_at) : kt("neverChecked", "未检查")}
        </Typography.Text>
        {row.last_check_latency_ms != null && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{row.last_check_latency_ms}ms</Typography.Text>
        )}
        {row.last_check_error_code && (
          <Typography.Text type="danger" style={{ fontSize: 12 }}>{row.last_check_error_code}</Typography.Text>
        )}
      </Space>
    ) },
    { title: kt("credentialRef", "凭据引用"), dataIndex: "secret_ref", key: "secret_ref", width: 200, render: (v: string | null) => (
      <Typography.Text code style={{ fontSize: 12 }}>{v ?? "-"}</Typography.Text>
    ) },
    { title: kt("actions", "操作"), key: "actions", width: 300, render: (_: unknown, row: ClusterInfo) => (
      <Space wrap>
        <Button size="small" icon={<ReloadOutlined />} loading={checkingId === row.id} onClick={() => handleCheck(row)}>
          {kt("check", "连通性检查")}
        </Button>
        <Button size="small" icon={<ClusterOutlined />} onClick={() => openNodes(row)}>{kt("nodes", "节点能力")}</Button>
        <Button size="small" onClick={() => openNamespaces(row)}>{kt("namespaces", "命名空间")}</Button>
        <Button size="small" onClick={() => openResourceGroups(row)}>{kt("resourceGroups", "资源组")}</Button>
        <Popconfirm title={kt("deleteConfirm", "确认下线该集群?")} onConfirm={() => handleDelete(row)}>
          <Button size="small" danger>{kt("offline", "下线")}</Button>
        </Popconfirm>
      </Space>
    ) },
  ];

  return (
    <AppLayout>
      <div>
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <Space wrap style={{ justifyContent: "space-between", width: "100%" }}>
            <Space wrap>
              <Typography.Title level={4} style={{ margin: 0 }}>{kt("title", "Kubernetes 集群")}</Typography.Title>
              <Select
                style={{ minWidth: 220 }}
                placeholder={kt("selectProject", "选择项目")}
                value={projectId ?? undefined}
                options={projects.map((p) => ({ value: p.id, label: p.name }))}
                onChange={(value) => setProjectId(value)}
              />
            </Space>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={loadClusters}>{kt("refresh", "刷新")}</Button>
              <Button type="primary" onClick={() => setRegisterOpen(true)} disabled={!projectId}>
                {kt("register", "登记集群")}
              </Button>
            </Space>
          </Space>

          <Alert
            type="info"
            showIcon
            message={kt("hint", "凭据只保存 env:/file: 引用,平台不存储任何 token 或 kubeconfig 内容;端点必须在 allowlist 内。")}
          />

          <Table
            rowKey="id"
            size="middle"
            loading={loading}
            columns={columns as never}
            dataSource={visibleClusters}
            pagination={{ pageSize: 10, showTotal: (total) => `${total}` }}
            locale={{ emptyText: kt("empty", "尚无登记集群") }}
          />
        </Space>

        <Modal
          title={kt("register", "登记集群")}
          open={registerOpen}
          onOk={handleRegister}
          onCancel={() => setRegisterOpen(false)}
          okText={kt("save", "保存")}
          cancelText={kt("cancel", "取消")}
          destroyOnHidden
        >
          <Form form={form} layout="vertical">
            <Form.Item name="name" label={kt("name", "标识名")} rules={[{ required: true }]}>
              <Input placeholder="w13-kind" />
            </Form.Item>
            <Form.Item name="display_name" label={kt("displayName", "显示名")}>
              <Input />
            </Form.Item>
            <Form.Item name="api_server_url" label="API Server" rules={[{ required: true }]}>
              <Input placeholder="https://127.0.0.1:6443" />
            </Form.Item>
            <Form.Item name="secret_ref" label={kt("secretRef", "凭据引用")} rules={[{ required: true }]}
              extra={kt("secretRefHint", "格式:env:变量名 或 file:/绝对路径;平台不保存凭据内容。")}>
              <Input placeholder="env:LINKRAFT_KIND_TOKEN" />
            </Form.Item>
            <Form.Item name="provider" label={kt("provider", "类型")} initialValue="generic">
              <Select options={[{ value: "generic", label: "generic" }, { value: "kind", label: "kind" }]} />
            </Form.Item>
            <Form.Item name="default_namespace" label={kt("defaultNamespace", "默认命名空间")}>
              <Input placeholder="linkraft-dev" />
            </Form.Item>
            <Form.Item name="insecure_tls" label={kt("insecureTls", "允许 insecure http/TLS(仅本地测试)")} valuePropName="checked">
              <Switch />
            </Form.Item>
          </Form>
        </Modal>

        <Drawer title={`${kt("nodes", "节点能力")} · ${nodesTarget?.name ?? ""}`} width={640} open={!!nodesTarget} onClose={() => setNodesTarget(null)}>
          <Table
            rowKey="hostname"
            size="small"
            dataSource={nodes ?? []}
            loading={nodes === null}
            pagination={false}
            columns={[
              { title: "hostname", dataIndex: "hostname", key: "hostname" },
              { title: "arch", dataIndex: "arch", key: "arch", width: 90 },
              { title: "CPU", dataIndex: "cpu_cores", key: "cpu", width: 90 },
              { title: "memory", dataIndex: "memory", key: "memory", width: 110 },
              { title: "GPU", dataIndex: "gpu", key: "gpu", width: 80 },
            ]}
          />
        </Drawer>

        <Drawer title={`${kt("namespaces", "命名空间")} · ${nsTarget?.name ?? ""}`} width={520} open={!!nsTarget} onClose={() => setNsTarget(null)}>
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            {liveNamespaces === null ? null : (
              <Space wrap>
                {liveNamespaces.map((name) => <Tag key={name}>{name}</Tag>)}
                {liveNamespaces.length === 0 && <Typography.Text type="secondary">{kt("empty", "尚无登记集群")}</Typography.Text>}
              </Space>
            )}
            <Form form={nsForm} layout="inline">
              <Form.Item name="namespaceName" rules={[{ required: true }]}>
                <Input placeholder={kt("namespaceName", "命名空间名")} />
              </Form.Item>
              <Form.Item name="cpuCores">
                <Input placeholder="cpu_cores" style={{ width: 110 }} />
              </Form.Item>
              <Form.Item name="memoryMb">
                <Input placeholder="memory_mb" style={{ width: 110 }} />
              </Form.Item>
              <Button type="primary" onClick={handleEnsureNamespace}>{kt("ensure", "确保存在")}</Button>
            </Form>
          </Space>
        </Drawer>

        <Drawer title={`${kt("resourceGroups", "资源组")} · ${rgTarget?.name ?? ""}`} width={560} open={!!rgTarget} onClose={() => setRgTarget(null)}>
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <Table
              rowKey="id"
              size="small"
              dataSource={resourceGroups ?? []}
              loading={resourceGroups === null}
              pagination={false}
              columns={[
                { title: kt("name", "标识名"), dataIndex: "name", key: "name" },
                { title: "policy", dataIndex: "scheduling_policy_json", key: "policy", render: (v: Record<string, unknown>) => String(v?.policy_type ?? "-") },
                { title: "quota", dataIndex: "quota_json", key: "quota", render: (v: Record<string, number>) => Object.keys(v).length ? JSON.stringify(v) : "-" },
                { title: kt("status", "状态"), dataIndex: "status", key: "status", width: 90 },
              ]}
            />
            <Form form={rgForm} layout="inline">
              <Form.Item name="groupName" rules={[{ required: true }]}>
                <Input placeholder={kt("name", "标识名")} />
              </Form.Item>
              <Form.Item name="cpuCores">
                <Input placeholder="cpu_cores" style={{ width: 110 }} />
              </Form.Item>
              <Form.Item name="memoryMb">
                <Input placeholder="memory_mb" style={{ width: 110 }} />
              </Form.Item>
              <Button type="primary" onClick={handleCreateResourceGroup}>{kt("save", "保存")}</Button>
            </Form>
          </Space>
        </Drawer>
      </div>
    </AppLayout>
  );
}
