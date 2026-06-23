import { useState, useEffect } from "react";
import { Card, Table, Tag, Button, Space, Typography, Modal, Input, Select, Form, message, Progress } from "antd";
import { PlusOutlined, EditOutlined, DeleteOutlined, CloudServerOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import { apiGet, apiPost, apiPut, apiDelete } from "../api/client";

const { Title } = Typography;
const stColor: Record<string, string> = { online: "green", offline: "red", busy: "orange" };
const stName: Record<string, string> = { online: "在线", offline: "离线", busy: "忙碌" };

export default function ComputeResourcePage() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  const [form] = Form.useForm();

  useEffect(() => { fetchData(); }, []);

  const fetchData = async () => {
    setLoading(true);
    try { const res: any = await apiGet("/api/compute/nodes"); setData(res.items || []); }
    finally { setLoading(false); }
  };

  const handleSubmit = async (values: any) => {
    if (editing) {
      await apiPut("/api/compute/nodes/" + editing.id, values);
      message.success("更新成功");
    } else {
      await apiPost("/api/compute/nodes", values);
      message.success("创建成功");
    }
    setShowModal(false); setEditing(null); form.resetFields(); fetchData();
  };

  const handleDelete = async (id: string) => {
    await apiDelete("/api/compute/nodes/" + id);
    message.success("删除成功"); fetchData();
  };

  const columns = [
    { title: "节点名称", dataIndex: "name", key: "name",
      render: (t:string) => <Space><CloudServerOutlined />{t}</Space> },
    { title: "编号", dataIndex: "node_number", key: "node_number" },
    { title: "IP地址", dataIndex: "ip_address", key: "ip_address" },
    { title: "类型", dataIndex: "node_type", key: "node_type",
      render: (t:string) => <Tag color={t==="gpu"?"purple":"blue"}>{t.toUpperCase()}</Tag> },
    { title: "状态", dataIndex: "status", key: "status",
      render: (s:string) => <Tag color={stColor[s]}>{stName[s]||s}</Tag> },
    { title: "用途", dataIndex: "purpose", key: "purpose",
      render: (p:string) => <Tag>{p==="training"?"训练":p==="inference"?"推理":"混合"}</Tag> },
    { title: "CPU核", dataIndex: "cpu_cores", key: "cpu_cores" },
    { title: "GPU数", dataIndex: "gpu_count", key: "gpu_count" },
    { title: "内存GB", dataIndex: "memory_gb", key: "memory_gb" },
    { title: "负载", dataIndex: "current_load", key: "current_load",
      render: (v:number) => <Progress percent={Math.round(v||0)} size="small" /> },
    { title: "操作", key: "actions",
      render: (_:any, r:any) => (
        <Space>
          <Button size="small" icon={<EditOutlined />}
            onClick={() => { setEditing(r); form.setFieldsValue(r); setShowModal(true); }}>编辑</Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(r.id)}>删除</Button>
        </Space>
      )},
  ];

  return (
    <AppLayout>
      <Card title={<Title level={4}>计算资源管理</Title>}
        extra={<Button type="primary" icon={<PlusOutlined />}
          onClick={() => { setEditing(null); form.resetFields(); setShowModal(true); }}>新增节点</Button>}>
        <Table dataSource={data} columns={columns} rowKey="id" loading={loading} size="small" scroll={{ x: 1100 }} />
      </Card>
      <Modal title={editing ? "编辑节点" : "新增节点"} open={showModal}
        onCancel={() => { setShowModal(false); setEditing(null); }}
        onOk={() => form.submit()} width={600}>
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item name="name" label="节点名称" rules={[{required:true}]}><Input /></Form.Item>
          <Form.Item name="ip_address" label="IP地址"><Input /></Form.Item>
          <Form.Item name="node_type" label="节点类型">
            <Select options={[{value:"cpu",label:"CPU"},{value:"gpu",label:"GPU"}]} /></Form.Item>
          <Form.Item name="purpose" label="用途">
            <Select options={[{value:"training",label:"训练"},{value:"inference",label:"推理"},{value:"hybrid",label:"混合"}]} /></Form.Item>
          <Form.Item name="cpu_cores" label="CPU核数"><Input type="number" /></Form.Item>
          <Form.Item name="gpu_count" label="GPU数量"><Input type="number" /></Form.Item>
          <Form.Item name="memory_gb" label="内存(GB)"><Input type="number" /></Form.Item>
          <Form.Item name="disk_gb" label="磁盘(GB)"><Input type="number" /></Form.Item>
          <Form.Item name="current_load" label="当前负载(%)"><Input type="number" /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  );
}
