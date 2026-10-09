import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, Empty, Form, Input, Modal, Select, Space, Table, Typography, message } from "antd";
import { ApiOutlined, CloudUploadOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import AppLayout from "../components/AppLayout";
import DeleteConfirmation from "../components/DeleteConfirmation";
import apiClient, { apiGet, apiPost, formatApiError } from "../api/client";
import { useI18n } from "../i18n";

const { Title, Text } = Typography;

export default function OrchestrationPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const tr = ((t as unknown as Record<string, Record<string, string | undefined>>).orchestration ?? {}) as Record<string, string | undefined>;

  const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [creating, setCreating] = useState(false);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [form] = Form.useForm();

  useEffect(() => {
    apiGet("/projects").then((res: any) => {
      const items = res.items || [];
      setProjects(items);
      if (items.length) setProjectId(items[0].id);
    }).catch((error) => message.error(formatApiError(error, "项目加载失败")));
  }, []);

  const loadWorkflows = useCallback(async (pid: string) => {
    if (!pid) { setWorkflows([]); return; }
    setLoading(true);
    setLoadError("");
    try {
      const res: any = await apiGet(`/projects/${pid}/workflows`);
      setWorkflows(res.items || res || []);
    } catch (error) {
      setWorkflows([]);
      setLoadError(formatApiError(error, "工作流加载失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadWorkflows(projectId); }, [projectId, loadWorkflows]);

  const createWorkflow = async (values: any) => {
    setCreating(true);
    try {
      const res: any = await apiPost(`/projects/${projectId}/workflows`, {
        name: values.name,
        description: values.description || "",
        nodes: [],
        edges: [],
      });
      message.success(tr.created || "服务图已创建");
      setCreating(false);
      navigate(`/workspace/${res.data?.id || res.id}`);
    } catch (error) {
      setCreating(false);
      message.error(formatApiError(error, "创建失败"));
    }
  };

  // 方案B：发布最新已保存草稿为版本，并注册为编排 API。
  const publishAsApi = async (record: any) => {
    setPublishingId(record.id);
    try {
      const version: any = await apiClient.post(`/workflows/${record.id}/publish`).then((r: any) => r.data);
      const api: any = await apiClient.post(
        `/platform/apis/publish/workflow/${record.id}/${version.version}`,
      ).then((r: any) => r.data);
      message.success(`${tr.published || "已发布为编排 API"}：${api.name}`);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      message.error(typeof detail === "object" && detail?.message ? detail.message : (detail || formatApiError(error, "发布失败")));
    } finally {
      setPublishingId(null);
    }
  };

  const deleteWorkflow = async (wfId: string) => {
    try {
      await apiClient.delete(`/projects/${projectId}/workflows/${wfId}`);
      message.success(tr.deleted || "已删除");
      loadWorkflows(projectId);
    } catch (error) {
      message.error(formatApiError(error, "删除失败"));
    }
  };

  const columns = [
    { title: tr.name || "名称", dataIndex: "name", key: "name", ellipsis: true },
    { title: tr.description || "描述", dataIndex: "description", key: "description", ellipsis: true,
      render: (v: string) => v || "-" },
    { title: tr.updated || "更新时间", dataIndex: "updated_at", key: "updated_at", width: 180,
      render: (v: string) => v ? v.replace("T", " ").slice(0, 19) : "-" },
    { title: tr.actions || "操作", key: "actions", width: 320,
      render: (_: unknown, record: any) => (
        <Space size="small">
          <Button size="small" type="primary" icon={<EditOutlined />}
            onClick={() => navigate(`/workspace/${record.id}`)}>
            {tr.edit || "编辑图"}
          </Button>
          <Button size="small" icon={<ApiOutlined />} loading={publishingId === record.id}
            onClick={() => void publishAsApi(record)}>
            {tr.publish_api || "发布为 API"}
          </Button>
          <DeleteConfirmation label={`删除 ${record.name}`} targetName={record.name}
            onConfirm={() => void deleteWorkflow(record.id)} />
        </Space>
      ) },
  ];

  return (
    <AppLayout>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap size="large" align="center">
          <Title level={3} style={{ margin: 0 }}>
            <ApiOutlined /> {tr.title || "应用编排 · 服务图"}
          </Title>
          <span>
            <Text type="secondary">{tr.project || "项目"}</Text>
            <Select
              style={{ minWidth: 220, marginLeft: 8 }}
              value={projectId || undefined}
              onChange={(value) => setProjectId(value)}
              options={projects.map((p) => ({ value: p.id, label: p.name }))}
              placeholder={tr.choose_project || "选择项目"}
            />
          </span>
          <Button icon={<PlusOutlined />} type="primary" disabled={!projectId}
            onClick={() => setCreating(true)}>
            {tr.new_workflow || "新建服务图"}
          </Button>
          <Button icon={<ReloadOutlined />} disabled={!projectId}
            onClick={() => loadWorkflows(projectId)}>
            {tr.refresh || "刷新"}
          </Button>
          <Button icon={<CloudUploadOutlined />} onClick={() => navigate("/api-marketplace")}>
            {tr.go_market || "前往 API 市场"}
          </Button>
        </Space>
        <Alert
          style={{ marginTop: 14 }}
          type="info"
          showIcon
          message={
            "服务图搭好后点「发布为 API」即可在 API 市场逐行调用。闭环算子（追加报错数据集 / 告警通知管理员 / 重训阈值判断）"
            + "与推理算子（冻结模型 / 应用模型 / 条件分支）均可在画布左侧算子面板拖入。"
          }
        />
      </Card>

      <Card>
        {loadError && <Alert type="error" showIcon message={loadError} style={{ marginBottom: 12 }} />}
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={workflows}
          pagination={false}
          locale={{ emptyText: <Empty description={projectId ? (tr.empty || "该项目还没有服务图，点「新建服务图」开始编排") : (tr.choose_project_first || "请先选择项目")} /> }}
        />
      </Card>

      <Modal
        title={tr.new_workflow || "新建服务图"}
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={() => form.submit()}
        confirmLoading={creating}
        okText={tr.create || "创建并进入画布"}
      >
        <Form form={form} layout="vertical" onFinish={createWorkflow}>
          <Form.Item name="name" label={tr.name || "名称"} rules={[{ required: true, message: tr.name_required || "请输入名称" }]}>
            <Input maxLength={128} placeholder={tr.name_placeholder || "如：焊接质量推理服务"} />
          </Form.Item>
          <Form.Item name="description" label={tr.description || "描述"}>
            <Input.TextArea rows={2} maxLength={512} placeholder={tr.desc_placeholder || "服务用途说明（可选）"} />
          </Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  );
}
