import { useState, useEffect } from "react";
import { Card, Table, Tag, Button, Space, Typography, Modal, Input, Select, Form, message, Progress, Row, Col } from "antd";
import { PlusOutlined, ThunderboltOutlined, EyeOutlined, DeleteOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import AnnotationCanvas from "../components/AnnotationCanvas";
import { apiGet, apiPost, apiPut, apiDelete } from "../api/client";

const { Title } = Typography;
const stColor: Record<string, string> = { pending: "default", labeling: "blue", review: "orange", completed: "green" };
const stName: Record<string, string> = { pending: "待标注", labeling: "标注中", review: "审核中", completed: "已完成" };

export default function AnnotationPage() {
  const [loading, setLoading] = useState(false);
  const [tasks, setTasks] = useState<any[]>([]);
  const [samples, setSamples] = useState<any[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [showSamples, setShowSamples] = useState(false);
  const [showCanvas, setShowCanvas] = useState(false);
  const [canvasSample, setCanvasSample] = useState<any>(null);
  const [selectedTask, setSelectedTask] = useState<any>(null);
  const [form] = Form.useForm();

  useEffect(() => { fetchTasks(); }, []);

  const fetchTasks = async () => {
    setLoading(true);
    try { const res: any = await apiGet("/annotations/tasks"); setTasks(res.items || []); }
    finally { setLoading(false); }
  };

  const fetchSamples = async (taskId: string) => {
    try { const res: any = await apiGet("/annotations/tasks/" + taskId + "/samples"); setSamples(res.items || []); }
    catch { setSamples([]); }
  };

  const handleCreate = async (values: any) => {
    await apiPost("/annotations/tasks", values);
    message.success("创建成功"); setShowCreate(false); fetchTasks();
  };

  const handleDelete = async (id: string) => {
    await apiDelete("/annotations/tasks/" + id);
    message.success("删除成功"); fetchTasks();
  };

  const handleUpdateSample = async (sampleId: string, status: string) => {
    await apiPut("/annotations/samples/" + sampleId, { status });
    fetchSamples(selectedTask.id);
    fetchTasks();
  };

  const handleAutoLabel = async (taskId: string) => {
    await apiPost("/annotations/tasks/" + taskId + "/auto-label");
    message.success("自动标注完成"); fetchTasks();
    if (selectedTask) fetchSamples(selectedTask.id);
  };

  const columns = [
    { title: "任务名称", dataIndex: "name", key: "name" },
    { title: "标注类型", dataIndex: "annotation_type", key: "annotation_type",
      render: (t:string) => <Tag>{t==="rectangle"?"矩形":t==="polygon"?"多边形":t==="point"?"点":t}</Tag> },
    { title: "状态", dataIndex: "status", key: "status",
      render: (s:string) => <Tag color={stColor[s]||"default"}>{stName[s]||s}</Tag> },
    { title: "进度", key: "progress",
      render: (_:any, r:any) => r.total_samples > 0
        ? <Progress percent={Math.round((r.labeled_samples/r.total_samples)*100)} size="small"
            format={() => r.labeled_samples + "/" + r.total_samples} />
        : <span style={{color:"#999"}}>-</span> },
    { title: "已审核", dataIndex: "reviewed_samples", key: "reviewed_samples" },
    { title: "创建时间", dataIndex: "created_at", key: "created_at",
      render: (t:string) => t ? new Date(t).toLocaleDateString() : "-" },
    { title: "操作", key: "actions",
      render: (_:any, r:any) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => { setSelectedTask(r); fetchSamples(r.id); setShowSamples(true); }}>样本</Button>
          <Button size="small" icon={<ThunderboltOutlined />} onClick={() => handleAutoLabel(r.id)}>自动标注</Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(r.id)}>删除</Button>
        </Space>
      )},
  ];

  const sampleColumns = [
    { title: "#", dataIndex: "sample_index", key: "sample_index", width: 60 },
    { title: "样本路径", dataIndex: "sample_path", key: "sample_path", ellipsis: true },
    { title: "状态", dataIndex: "status", key: "status",
      render: (s:string) => <Tag color={s==="unlabeled"?"default":s==="labeled"?"blue":s==="reviewed"?"green":"orange"}>{s==="unlabeled"?"未标注":s==="labeled"?"已标注":s==="reviewed"?"已审核":s}</Tag> },
    { title: "自动标注", dataIndex: "is_auto_labeled", key: "is_auto_labeled",
      render: (v:boolean) => v ? <Tag color="purple">是</Tag> : <Tag>否</Tag> },
    { title: "标注数", dataIndex: "annotations", key: "annotations",
      render: (a:any[]) => (a||[]).length },
    { title: "操作", key: "actions",
      render: (_:any, s:any) => (
        <Space>
          <Button size="small" type="primary" onClick={() => { setCanvasSample(s); setShowCanvas(true); }}>标注</Button>
          {s.status === "unlabeled" && <Button size="small" onClick={() => handleUpdateSample(s.id, "labeled")}>标记完成</Button>}
          {s.status === "labeled" && <Button size="small" onClick={() => handleUpdateSample(s.id, "reviewed")}>审核通过</Button>}
        </Space>
      )},
  ];

  return (
    <AppLayout>
      <Card title={<Title level={4}>标注工具</Title>}
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setShowCreate(true)}>新建标注任务</Button>}>
        <Table dataSource={tasks} columns={columns} rowKey="id" loading={loading} size="small" />
      </Card>

      <Modal title="新建标注任务" open={showCreate} onCancel={() => setShowCreate(false)} onOk={() => form.submit()} width={500}>
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item name="name" label="任务名称" rules={[{required:true}]}><Input /></Form.Item>
          <Form.Item name="dataset_id" label="数据集ID" rules={[{required:true}]}><Input /></Form.Item>
          <Form.Item name="annotation_type" label="标注类型" initialValue="rectangle">
            <Select options={[{value:"rectangle",label:"矩形标注"},{value:"polygon",label:"多边形标注"},{value:"point",label:"点标注"},{value:"line",label:"线标注"}]} />
          </Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item>
          <Form.Item name="guidelines" label="标注规范"><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>

      <Modal title={selectedTask ? "样本列表 - " + selectedTask.name : ""} open={showSamples}
        onCancel={() => { setShowSamples(false); setSelectedTask(null); }} footer={null} width={900}>
        <Table dataSource={samples} columns={sampleColumns} rowKey="id" size="small" pagination={{ pageSize: 20 }} />
      </Modal>
          <Modal title="在线标注" open={showCanvas} onCancel={() => setShowCanvas(false)} footer={null} width={900}>
        {canvasSample && <AnnotationCanvas sampleId={canvasSample.id} imageUrl={canvasSample.sample_path} existingAnnotations={canvasSample.annotations||[]} onSave={() => { fetchSamples(selectedTask?.id); fetchTasks(); }} />}
      </Modal>
    </AppLayout>
  );
}

