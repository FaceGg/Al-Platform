import { useState, useEffect } from "react";
import { Card, Table, Tag, Button, Space, Typography, Modal, Input, Select, Form, message, Descriptions, Tabs } from "antd";
import { PlusOutlined, EyeOutlined, DeleteOutlined, SendOutlined, HistoryOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import { apiGet, apiPost, apiDelete } from "../api/client";

const { Title } = Typography;
const stColor: Record<string, string> = { draft: "default", published: "green", offline: "red" };
const stName: Record<string, string> = { draft: "草稿", published: "已发布", offline: "已下线" };

export default function OrchestrationPage() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any[]>([]);
  const [agents, setAgents] = useState<any[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [showAgent, setShowAgent] = useState(false);
  const [selected, setSelected] = useState<any>(null);
  const [createForm] = Form.useForm();
  const [agentForm] = Form.useForm();

  useEffect(() => { fetchData(); fetchAgents(); }, []);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res: any = await apiGet("/orchestration/tasks");
      setData(res.items || []);
    } catch { setData([]); }
    finally { setLoading(false); }
  };

  const fetchAgents = async () => {
    try {
      const res: any = await apiGet("/orchestration/agents");
      setAgents(res.items || res || []);
    } catch { setAgents([]); }
  };

  const handleCreateTask = async (values: any) => {
    await apiPost("/orchestration/tasks", values);
    message.success("任务创建成功");
    setShowCreate(false);
    fetchData();
  };

  const handleCreateAgent = async (values: any) => {
    await apiPost("/orchestration/agents", values);
    message.success("智能体创建成功");
    setShowAgent(false);
    fetchAgents();
  };

  const handlePlan = async (taskId: string) => {
    await apiPost("/orchestration/plan", { task_id: taskId });
    message.success("任务规划已触发");
    fetchData();
  };

  const taskColumns = [
    { title: "任务名称", dataIndex: "name", key: "name" },
    { title: "状态", dataIndex: "status", key: "status",
      render: (s:string) => <Tag color={s==="pending"?"default":s==="running"?"blue":s==="completed"?"green":"red"}>{s==="pending"?"待处理":s==="running"?"运行中":s==="completed"?"已完成":s==="failed"?"失败":s}</Tag> },
    { title: "优先级", dataIndex: "priority", key: "priority",
      render: (p:number) => <Tag color={p>5?"red":p>2?"orange":"green"}>{p}</Tag> },
    { title: "指定智能体", dataIndex: "assigned_agent_id", key: "assigned_agent_id",
      render: (id:string) => id ? <Tag color="purple">{agents.find((a:any)=>a.id===id)?.name||id.slice(0,8)}</Tag> : "-" },
    { title: "需审核", dataIndex: "requires_review", key: "requires_review",
      render: (v:boolean) => v ? <Tag color="orange">是</Tag> : <Tag>否</Tag> },
    { title: "创建时间", dataIndex: "created_at", key: "created_at",
      render: (t:string) => t ? new Date(t).toLocaleDateString() : "-" },
    { title: "操作", key: "actions",
      render: (_:any, r:any) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => { setSelected(r); setShowDetail(true); }}>详情</Button>
          <Button size="small" icon={<SendOutlined />} onClick={() => handlePlan(r.id)}>规划</Button>
        </Space>
      )},
  ];

  const agentColumns = [
    { title: "智能体名称", dataIndex: "name", key: "name" },
    { title: "类型", dataIndex: "agent_type", key: "agent_type",
      render: (t:string) => {
        const names: Record<string,string> = { planner:"调度者", llm:"大模型", executor:"执行者", reviewer:"审核者" };
        return <Tag>{names[t]||t}</Tag>;
      }},
    { title: "模型", dataIndex: "model_name", key: "model_name", render: (m:string) => <Tag color="blue">{m||"default"}</Tag> },
    { title: "状态", dataIndex: "is_active", key: "is_active",
      render: (v:boolean) => <Tag color={v?"green":"red"}>{v?"活跃":"停用"}</Tag> },
  ];

  return (
    <AppLayout>
      <Space direction="vertical" size="large" style={{ width: "100%" }}>
        <Card title={<Title level={4}>多智能体协同</Title>}
          extra={<Space>
            <Button icon={<PlusOutlined />} onClick={() => setShowAgent(true)}>新增智能体</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowCreate(true)}>新建任务</Button>
          </Space>}>
          <Tabs defaultActiveKey="tasks" items={[
            {
              key: "tasks", label: "协同任务",
              children: <Table dataSource={data} columns={taskColumns} rowKey="id" loading={loading} size="small" />
            },
            {
              key: "agents", label: "智能体列表",
              children: <Table dataSource={agents} columns={agentColumns} rowKey="id" size="small" />
            },
          ]} />
        </Card>

        <Card title="协同架构说明" size="small">
          <Descriptions column={1} size="small">
            <Descriptions.Item label="调度者(Planner)">负责任务分解、规划与分配，协调各智能体协同工作</Descriptions.Item>
            <Descriptions.Item label="大模型(LLM)">负责自然语言理解、知识推理、结果整合与生成</Descriptions.Item>
            <Descriptions.Item label="执行者(Executor)">负责专业计算、算法调用、模型推理等具体任务</Descriptions.Item>
            <Descriptions.Item label="审核者(Reviewer)">负责关键决策节点的审核与确认，提供人机协同接口</Descriptions.Item>
          </Descriptions>
        </Card>
      </Space>

      <Modal title="新建协同任务" open={showCreate} onCancel={() => setShowCreate(false)} onOk={() => createForm.submit()} width={500}>
        <Form form={createForm} layout="vertical" onFinish={handleCreateTask}>
          <Form.Item name="name" label="任务名称" rules={[{required:true}]}><Input /></Form.Item>
          <Form.Item name="description" label="任务描述"><Input.TextArea rows={3} /></Form.Item>
          <Form.Item name="priority" label="优先级" initialValue={5}>
            <Select options={[1,2,3,5,8,10].map(v=>({value:v,label:"P"+v}))} />
          </Form.Item>
          <Form.Item name="requires_review" label="需要人工审核" initialValue={false}>
            <Select options={[{value:true,label:"是"},{value:false,label:"否"}]} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="新增智能体" open={showAgent} onCancel={() => setShowAgent(false)} onOk={() => agentForm.submit()} width={500}>
        <Form form={agentForm} layout="vertical" onFinish={handleCreateAgent}>
          <Form.Item name="name" label="智能体名称" rules={[{required:true}]}><Input /></Form.Item>
          <Form.Item name="agent_type" label="智能体类型" initialValue="executor">
            <Select options={[{value:"planner",label:"调度者"},{value:"llm",label:"大模型"},{value:"executor",label:"执行者"},{value:"reviewer",label:"审核者"}]} />
          </Form.Item>
          <Form.Item name="model_name" label="关联模型"><Input placeholder="如 gpt-3.5-turbo" /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>

      <Modal title="任务详情" open={showDetail} onCancel={() => setShowDetail(false)} footer={null} width={600}>
        {selected && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="名称">{selected.name}</Descriptions.Item>
            <Descriptions.Item label="状态"><Tag>{selected.status}</Tag></Descriptions.Item>
            <Descriptions.Item label="优先级">{selected.priority}</Descriptions.Item>
            <Descriptions.Item label="需审核">{selected.requires_review?"是":"否"}</Descriptions.Item>
            <Descriptions.Item label="审核状态">{selected.review_status||"无"}</Descriptions.Item>
            <Descriptions.Item label="指定智能体">{agents.find((a:any)=>a.id===selected.assigned_agent_id)?.name||"-"}</Descriptions.Item>
            <Descriptions.Item label="描述" span={2}>{selected.description||"-"}</Descriptions.Item>
            <Descriptions.Item label="输入数据" span={2}><pre>{JSON.stringify(selected.input_data||{},null,2)}</pre></Descriptions.Item>
            <Descriptions.Item label="输出数据" span={2}><pre>{JSON.stringify(selected.output_data||{},null,2)}</pre></Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </AppLayout>
  );
}

