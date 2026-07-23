import { useState, useEffect } from "react";
import { Card, Table, Tag, Button, Space, Typography, Modal, Input, Select, Form, message, Descriptions, Tabs, List, Timeline, Badge, Empty } from "antd";
import { PlusOutlined, EyeOutlined, DeleteOutlined, SendOutlined, CheckOutlined, CloseOutlined, MessageOutlined, RobotOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import apiClient, { apiGet, apiPost, apiDelete } from "../api/client";
import { useI18n } from "../i18n";

const { Title, Text, Paragraph } = Typography;
const stColor: Record<string, string> = { pending: "default", running: "blue", completed: "green", failed: "red", in_progress: "processing" };
const agentTypeNames: Record<string, { zh: string; en: string }> = {
  planner: { zh: "规划智能体", en: "Planner" },
  llm: { zh: "大模型智能体", en: "LLM" },
  executor: { zh: "执行智能体", en: "Executor" },
  reviewer: { zh: "审核智能体", en: "Reviewer" },
};

export default function OrchestrationPage() {
  const { t, lang } = useI18n();
  const text = lang === "zh" ? {
    planCompleted: "规划完成", planFailed: "规划失败", deleteAgent: "删除智能体",
    batchDeleteAgent: "批量删除智能体", agentDeleted: "智能体已删除",
    deleteFailed: "删除失败", deleteSelectedAgents: "确定要删除选中的",
    agents: "个智能体吗？", no: "否", active: "活跃", disabled: "禁用",
    model: "模型", actions: "操作", type: "类型", status: "状态",
  } : {
    planCompleted: "Planning completed", planFailed: "Planning failed", deleteAgent: "Delete agent",
    batchDeleteAgent: "Delete selected agents", agentDeleted: "Agents deleted",
    deleteFailed: "Delete failed", deleteSelectedAgents: "Delete selected",
    agents: "agents?", no: "No", active: "Active", disabled: "Disabled",
    model: "Model", actions: "Actions", type: "Type", status: "Status",
  };
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any[]>([]);
  const [agents, setAgents] = useState<any[]>([]);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [agentSelectedKeys, setAgentSelectedKeys] = useState<React.Key[]>([]);
  const [showDetail, setShowDetail] = useState(false);
  const [showAgent, setShowAgent] = useState(false);
  const [showReview, setShowReview] = useState(false);
  const [showMessages, setShowMessages] = useState(false);
  const [selected, setSelected] = useState<any>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [reviews, setReviews] = useState<any[]>([]);
  const [reviewComment, setReviewComment] = useState("");
  const [activeTab, setActiveTab] = useState("tasks");
  const [createForm] = Form.useForm();
  const [agentForm] = Form.useForm();

  useEffect(() => { fetchData(); fetchAgents(); fetchReviews(); }, []);

  const fetchData = async () => {
    setLoading(true);
    try { const res: any = await apiGet("/orchestration/tasks"); setData(res.items || res || []); }
    catch { setData([]); }
    finally { setLoading(false); }
  };

  const fetchAgents = async () => {
    try { const res: any = await apiGet("/orchestration/agents"); setAgents(res.items || res || []); }
    catch { setAgents([]); }
  };

  const fetchReviews = async () => {
    try { const res: any = await apiGet("/orchestration/reviews"); setReviews(res.reviews || []); }
    catch { setReviews([]); }
  };

  const fetchMessages = async (taskId: string) => {
    try { const res: any = await apiGet("/orchestration/tasks/" + taskId + "/messages"); setMessages(res.items || res || []); }
    catch { setMessages([]); }
  };

  const handleCreateTask = async (values: any) => {
    await apiPost("/orchestration/tasks", values);
    message.success(t.common.success);
    setShowCreate(false); createForm.resetFields(); fetchData();
  };

  const handleCreateAgent = async (values: any) => {
    await apiPost("/orchestration/agents", values);
    message.success(t.common.success);
    setShowAgent(false); agentForm.resetFields(); fetchAgents();
  };

  const handlePlan = async (task: any) => {
    try {
      await apiPost("/orchestration/plan", {
        task_id: task.id,
        task_description: task.description || task.name,
      });
      message.success(text.planCompleted);
      fetchData();
    } catch (error: any) {
      message.error(error.response?.data?.detail || text.planFailed);
    }
  };

  const handleReview = async (taskId: string, approved: boolean) => {
    await apiPost("/orchestration/reviews/" + taskId, { approved, comment: reviewComment });
    message.success(approved ? "已审核通过" : "已拒绝");
    setReviewComment(""); setShowReview(false); fetchData(); fetchReviews();
  };

  const handleDeleteTask = async (taskId: string) => {
    Modal.confirm({
      title: t.common.delete + "任务",
      okType: "danger",
      onOk: async () => { await apiDelete("/orchestration/tasks/" + taskId); message.success(t.common.success); fetchData(); },
    });
  };


  const handleBatchDelete = async () => {
    Modal.confirm({
      title: "确定要删除选中的 " + selectedRowKeys.length + " 个任务吗？",
      okType: "danger",
      okText: "删除",
      cancelText: "取消",
      onOk: async () => {
        try {
          await apiClient.post("/orchestration/batch-delete", { ids: selectedRowKeys });
          message.success("批量删除成功");
          setSelectedRowKeys([]);
          fetchData();
        } catch {
          message.error("批量删除失败");
        }
      },
    });
  };


  const handleBatchDeleteAgent = async () => {
    if (agentSelectedKeys.length === 0) return;
    Modal.confirm({
      title: "确定要删除选中的 " + agentSelectedKeys.length + " 个智能体吗？",
      okType: "danger",
      okText: "删除",
      cancelText: "取消",
      onOk: async () => {
        try {
          await apiClient.post("/orchestration/agents/batch-delete", { ids: agentSelectedKeys });
          message.success(text.agentDeleted);
          setAgentSelectedKeys([]);
          fetchAgents();
        } catch {
          message.error(text.deleteFailed);
        }
      },
    });
  };

  const handleDeleteAgent = (agent: any) => {
    Modal.confirm({
      title: text.deleteAgent,
      content: agent.name,
      okType: "danger",
      onOk: async () => {
        try {
          await apiDelete("/orchestration/agents/" + agent.id);
          message.success(text.agentDeleted);
          setAgentSelectedKeys((keys) => keys.filter((key) => key !== agent.id));
          fetchAgents();
        } catch (error: any) {
          message.error(error.response?.data?.detail || text.deleteFailed);
        }
      },
    });
  };
  const taskColumns = [

    { title: t.knowledge?.name || "名称", dataIndex: "name", key: "name", ellipsis: true },
    { title: t.training?.status || "状态", dataIndex: "status", key: "status",
      render: (s: string) => <Tag color={stColor[s] || "default"}>{s}</Tag> },
    { title: "优先级", dataIndex: "priority", key: "priority",
      render: (p: number) => <Tag color={p > 5 ? "red" : p > 2 ? "orange" : "green"}>P{p}</Tag> },
    { title: t.orchestration?.assigned_agent || "智能体", dataIndex: "assigned_agent_id", key: "assigned_agent_id",
      render: (id: string) => id ? <Tag color="purple"><RobotOutlined /> {agents.find((a: any) => a.id === id)?.name || id.slice(0, 8)}</Tag> : "-" },
    { title: t.orchestration?.requires_review || "审核", dataIndex: "requires_review", key: "requires_review",
      render: (v: boolean) => v ? <Tag color="orange">待审核</Tag> : <Tag>否</Tag> },
    { title: t.training?.started || "创建时间", dataIndex: "created_at", key: "created_at",
      render: (t: string) => t ? new Date(t).toLocaleDateString() : "-" },
    { title: t.model?.actions || "操作", key: "actions",
      render: (_: any, r: any) => (
        <Space size="small">
          <Button size="small" icon={<EyeOutlined />} onClick={() => { setSelected(r); setShowDetail(true); }} />
          <Button size="small" icon={<SendOutlined />} onClick={() => handlePlan(r)}>{t.orchestration.plan}</Button>
          <Button size="small" icon={<MessageOutlined />} onClick={() => { setSelected(r); fetchMessages(r.id); setShowMessages(true); }} />
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDeleteTask(r.id)} />
        </Space>
      )},
  ];

  const agentColumns = [
    { title: t.knowledge?.name || "名称", dataIndex: "name", key: "name" },
    { title: text.type, dataIndex: "agent_type", key: "agent_type",
      render: (tp: string) => <Tag color={tp === "planner" ? "gold" : tp === "llm" ? "blue" : tp === "executor" ? "green" : "purple"}>{agentTypeNames[tp]?.[lang] || tp}</Tag> },
    { title: text.model, dataIndex: "model_name", key: "model_name", render: (m: string) => <Tag color="blue">{m || "-"}</Tag> },
    { title: text.status, dataIndex: "is_active", key: "is_active",
      render: (v: boolean) => <Badge status={v ? "success" : "error"} text={v ? text.active : text.disabled} /> },
    { title: text.actions, key: "actions", render: (_: any, agent: any) => (
      <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDeleteAgent(agent)}>{t.common.delete}</Button>
    ) },
  ];

  return (
    <AppLayout>
      <Space direction="vertical" size="large" style={{ width: "100%" }}>
        {reviews.length > 0 && (
          <Card size="small" title={<><Badge count={reviews.length} offset={[10, 0]}><CheckOutlined /></Badge> 待审核</>} style={{ borderColor: "#faad14" }}>
            <List size="small" dataSource={reviews} renderItem={(rv: any) => (
              <List.Item actions={[
                <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => { setSelected(rv); setShowReview(true); }}>审核</Button>
              ]}>
                <List.Item.Meta title={rv.name || rv.task_id} description={rv.description || ""} />
              </List.Item>
            )} />
          </Card>
        )}

        <Card title={<Title level={4}>{t.orchestration?.title || "多智能体编排"}</Title>}
          extra={<Space>
            {activeTab === "tasks" && selectedRowKeys.length > 0 && (
              <Button danger icon={<DeleteOutlined />} onClick={handleBatchDelete}>
                批量删除 ({selectedRowKeys.length})
              </Button>
            )}
            {activeTab === "agents" && agentSelectedKeys.length > 0 && (
              <Button danger icon={<DeleteOutlined />} onClick={handleBatchDeleteAgent}>
                {text.batchDeleteAgent} ({agentSelectedKeys.length})
              </Button>
            )}
            <Button icon={<PlusOutlined />} onClick={() => setShowAgent(true)}>{t.orchestration?.new_agent || "新建智能体"}</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowCreate(true)}>{t.orchestration?.new_task || "新建任务"}</Button>
          </Space>}>
          <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
            { key: "tasks", label: t.orchestration?.tasks || "任务",
              children: <Table dataSource={data} columns={taskColumns} rowKey="id" loading={loading} size="small" pagination={{ pageSize: 10 }} rowSelection={{ selectedRowKeys, onChange: (keys: React.Key[]) => setSelectedRowKeys(keys) }} /> },
            { key: "agents", label: t.orchestration?.agents || "智能体",
              children: <Table dataSource={agents} columns={agentColumns} rowKey="id" size="small" pagination={{ pageSize: 10 }} rowSelection={{ selectedRowKeys: agentSelectedKeys, onChange: (keys: React.Key[]) => setAgentSelectedKeys(keys) }} /> },
          ]} />
        </Card>

        <Card title="智能体架构" size="small">
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label={<Tag color="gold">{t.orchestration.planner}</Tag>}>负责任务解析、规划与分配</Descriptions.Item>
            <Descriptions.Item label={<Tag color="blue">LLM</Tag>}>NLU、自然语言理解与生成</Descriptions.Item>
            <Descriptions.Item label={<Tag color="green">{t.orchestration.executor}</Tag>}>专业计算、机理约束与小模型推理</Descriptions.Item>
            <Descriptions.Item label={<Tag color="purple">{t.orchestration.reviewer}</Tag>}>结果审核、质量控制与人工确认</Descriptions.Item>
          </Descriptions>
        </Card>
      </Space>

      <Modal title={t.orchestration?.new_task || "待审核"} open={showCreate} onCancel={() => setShowCreate(false)} onOk={() => createForm.submit()} width={500}>
        <Form form={createForm} layout="vertical" onFinish={handleCreateTask}>
          <Form.Item name="name" label={t.knowledge?.name || "名称"} rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label={t.knowledge?.desc || "取消"}><Input.TextArea rows={3} /></Form.Item>
          <Form.Item name="priority" label={t.orchestration?.priority || "待审核"} initialValue={5}>
            <Select options={[1, 2, 3, 5, 8, 10].map(v => ({ value: v, label: "P" + v }))} />
          </Form.Item>
          <Form.Item name="requires_review" label={t.orchestration?.requires_review || "待审核?"} initialValue={false}>
            <Select options={[{ value: true, label: "否" }, { value: false, label: "否" }]} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={t.orchestration?.new_agent || "待审核?"} open={showAgent} onCancel={() => setShowAgent(false)} onOk={() => agentForm.submit()} width={500}>
        <Form form={agentForm} layout="vertical" onFinish={handleCreateAgent}>
          <Form.Item name="name" label={t.knowledge?.name || "名称"} rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="agent_type" label={t.knowledge?.entity_type || "类型"} initialValue="executor">
            <Select options={[
              { value: "planner", label: "待审核" }, { value: "llm", label: "LLM" },
              { value: "executor", label: "待审核" }, { value: "reviewer", label: "待审核" }
            ]} />
          </Form.Item>
          <Form.Item name="model_name" label="取消"><Input placeholder="例如 gpt-4o-mini" /></Form.Item>
          <Form.Item name="description" label={t.knowledge?.desc || "取消"}><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>

      <Modal title="智能体架构" open={showMessages} onCancel={() => setShowMessages(false)} footer={null} width={700}>
        <Timeline items={messages.map((msg: any) => ({
          color: msg.message_type === "error" ? "red" : msg.message_type === "审核" ? "orange" : "blue",
          children: (
            <div>
              <Space><Tag>{msg.from_agent_id ? agents.find((a: any) => a.id === msg.from_agent_id)?.name || msg.from_agent_id.slice(0, 8) : "取消"}</Tag>
                <Text type="secondary">{new Date(msg.created_at).toLocaleTimeString()}</Text>
              </Space>
              <Paragraph style={{ marginTop: 4 }}>{msg.content}</Paragraph>
            </div>
          ),
        }))} />
        {messages.length === 0 && <Empty description="待审核?" />}
      </Modal>

      <Modal title="待审核?" open={showReview} onCancel={() => setShowReview(false)} footer={null} width={500}>
        {selected && (
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="取消">{selected.name || selected.task_id}</Descriptions.Item>
              <Descriptions.Item label="取消">{selected.description || "-"}</Descriptions.Item>
              <Descriptions.Item label="取消"><Tag>{selected.status}</Tag></Descriptions.Item>
            </Descriptions>
            <Input.TextArea rows={3} placeholder="待审核?..." value={reviewComment} onChange={e => setReviewComment(e.target.value)} />
            <Space>
              <Button type="primary" icon={<CheckOutlined />} onClick={() => handleReview(selected.task_id || selected.id, true)}>审核</Button>
              <Button danger icon={<CloseOutlined />} onClick={() => handleReview(selected.task_id || selected.id, false)}>审核</Button>
            </Space>
          </Space>
        )}
      </Modal>

      <Modal title="待审核?" open={showDetail} onCancel={() => setShowDetail(false)} footer={null} width={600}>
        {selected && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="取消">{selected.name}</Descriptions.Item>
            <Descriptions.Item label="取消"><Tag color={stColor[selected.status]}>{selected.status}</Tag></Descriptions.Item>
            <Descriptions.Item label="待审核">P{selected.priority}</Descriptions.Item>
            <Descriptions.Item label="取消">{selected.requires_review ? "取消" : "否"}</Descriptions.Item>
            <Descriptions.Item label="待审核?">{selected.review_status || "否"}</Descriptions.Item>
            <Descriptions.Item label="待审核">{agents.find((a: any) => a.id === selected.assigned_agent_id)?.name || "-"}</Descriptions.Item>
            <Descriptions.Item label="取消" span={2}>{selected.description || "-"}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </AppLayout>
  );
}
