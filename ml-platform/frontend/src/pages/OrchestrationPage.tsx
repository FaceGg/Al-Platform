import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, Empty, Form, Input, Modal, Select, Space, Table, Tag, Tooltip, Typography, message } from "antd";
import { ApiOutlined, CloudUploadOutlined, CopyOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import AppLayout from "../components/AppLayout";
import DeleteConfirmation from "../components/DeleteConfirmation";
import apiClient, { apiGet, apiPost, formatApiError } from "../api/client";
import { useI18n } from "../i18n";

const { Title, Text } = Typography;

interface WorkflowTemplateItem {
  id: string;
  name: string;
  description?: string | null;
  scope?: "project" | "global";
  node_count: number;
  updated_at: string | null;
}

const isPlatformAdmin = () => localStorage.getItem("role") === "admin";

export default function OrchestrationPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const tr = ((t as unknown as Record<string, Record<string, string | undefined>>).orchestration ?? {}) as Record<string, string | undefined>;

  const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [templates, setTemplates] = useState<WorkflowTemplateItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [instantiatingId, setInstantiatingId] = useState<string | null>(null);
  const [form] = Form.useForm();

  useEffect(() => {
    apiGet("/projects").then((res: any) => {
      const items = res.items || [];
      setProjects(items);
      if (items.length) setProjectId(items[0].id);
    }).catch((error) => message.error(formatApiError(error, "项目加载失败")));
  }, []);

  const loadWorkflows = useCallback(async (pid: string) => {
    if (!pid) { setWorkflows([]); setTemplates([]); return; }
    setLoading(true);
    setLoadError("");
    try {
      const [wfRes, tplRes] = await Promise.all([
        apiGet(`/projects/${pid}/workflows`),
        apiGet(`/projects/${pid}/workflow-templates`).catch(() => ({ items: [] })),
      ]);
      setWorkflows(wfRes.items || wfRes || []);
      setTemplates((tplRes.items || []) as WorkflowTemplateItem[]);
    } catch (error) {
      setWorkflows([]);
      setLoadError(formatApiError(error, "工作流加载失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadWorkflows(projectId); }, [projectId, loadWorkflows]);

  const createWorkflow = async (values: any) => {
    setSubmitting(true);
    try {
      // 选了模板 → 从模板实例化（图完整复制）；否则建空白服务图。
      const templateId = values.template_id as string | undefined;
      const res: any = templateId
        ? await apiPost(`/projects/${projectId}/workflow-templates/${templateId}/instantiate`, { name: values.name })
        : await apiPost(`/projects/${projectId}/workflows`, {
          name: values.name, description: values.description || "", nodes: [], edges: [],
        });
      message.success(templateId ? "已从模板创建服务图" : (tr.created || "服务图已创建"));
      setModalOpen(false);
      form.resetFields();
      navigate(`/workspace/${res.data?.id || res.id}`);
    } catch (error) {
      message.error(formatApiError(error, "创建失败"));
    } finally {
      setSubmitting(false);
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

  const deleteTemplate = async (tplId: string) => {
    try {
      await apiClient.delete(`/projects/${projectId}/workflows/${tplId}`);
      message.success("模板已删除");
      loadWorkflows(projectId);
    } catch (error) {
      message.error(formatApiError(error, "模板删除失败"));
    }
  };

  const instantiateTemplate = async (tpl: WorkflowTemplateItem) => {
    setInstantiatingId(tpl.id);
    try {
      const res: any = await apiPost(
        `/projects/${projectId}/workflow-templates/${tpl.id}/instantiate`,
        { name: `${tpl.name}-${new Date().toISOString().slice(5, 10)}` },
      );
      message.success(`已从模板创建：${res.data?.name || res.name}`);
      loadWorkflows(projectId);
    } catch (error) {
      message.error(formatApiError(error, "从模板创建失败"));
    } finally {
      setInstantiatingId(null);
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
            onClick={() => { form.resetFields(); setModalOpen(true); }}>
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
            + "与推理算子（冻结模型 / 应用模型 / 条件分支）均可在画布左侧算子面板拖入；搭好的图可在画布顶部「保存为模板」复用。"
          }
        />
      </Card>

      <Card
        title="服务图模板"
        size="small"
        style={{ marginBottom: 16 }}
        extra={<Text type="secondary" style={{ fontSize: 12 }}>画布顶部「保存为模板」可把当前服务图存为模板；编辑模板会直接改模板本身</Text>}
      >
        {templates.length === 0 ? (
          <Text type="secondary">暂无模板。打开一个服务图，点画布顶部的「保存为模板」即可沉淀为可复用模板。</Text>
        ) : (
          templates.map((tpl) => {
            const isGlobal = tpl.scope === "global";
            const canManage = !isGlobal || isPlatformAdmin();
            return (
              <div key={tpl.id} style={{
                display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
                padding: "6px 10px", marginBottom: 6, borderRadius: 6, background: "rgba(0,0,0,.03)",
              }}>
                <span>
                  <Text strong><CopyOutlined /> {tpl.name}</Text>
                  <Tag color={isGlobal ? "blue" : "default"} style={{ marginLeft: 8 }}>
                    {isGlobal ? "通用" : "项目"}
                  </Tag>
                  <Tag>{tpl.node_count} 节点</Tag>
                  {tpl.updated_at
                    ? <Text type="secondary" style={{ fontSize: 12 }}>{tpl.updated_at.replace("T", " ").slice(0, 16)}</Text>
                    : null}
                </span>
                <Space size={4}>
                  <Tooltip title={isGlobal ? "用此通用模板在当前项目创建服务图" : "用此模板在当前项目创建服务图"}>
                    <Button size="small" icon={<PlusOutlined />} loading={instantiatingId === tpl.id}
                      onClick={() => void instantiateTemplate(tpl)}>
                      从模板创建
                    </Button>
                  </Tooltip>
                  <Tooltip title={canManage ? undefined : "通用模板仅平台管理员可编辑"}>
                    <Button size="small" icon={<EditOutlined />} disabled={!canManage}
                      onClick={() => navigate(`/workspace/${tpl.id}`)}>
                      编辑
                    </Button>
                  </Tooltip>
                  {canManage && (
                    <DeleteConfirmation label={`删除模板 ${tpl.name}`} targetName={tpl.name}
                      onConfirm={() => void deleteTemplate(tpl.id)} />
                  )}
                </Space>
              </div>
            );
          })
        )}
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
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={submitting}
        okText={tr.create || "创建并进入画布"}
      >
        <Form form={form} layout="vertical" onFinish={createWorkflow}>
          <Form.Item name="template_id" label="从模板创建（可选）" initialValue="">
            <Select
              allowClear
              placeholder="不使用模板（空白服务图）"
              options={[
                { value: "", label: "不使用模板（空白服务图）" },
                ...templates.map((tpl) => ({
                  value: tpl.id,
                  label: `${tpl.name}（${tpl.node_count} 节点${tpl.scope === "global" ? " · 通用" : ""}）`,
                })),
              ]}
            />
          </Form.Item>
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
