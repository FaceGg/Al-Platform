import { useCallback, useEffect, useState } from "react";
import {
  Button, Card, Form, Input, Modal, Popconfirm, Progress, Select,
  Space, Table, Tabs, Tag, Typography, message,
} from "antd";
import {
  CloudServerOutlined, DeleteOutlined, EditOutlined, PlusOutlined,
  ReloadOutlined, ThunderboltOutlined,
} from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import { apiGet, apiPost, apiPut, apiDelete } from "../api/client";
import { parseBackendTime } from "../utils/time";

const { Title, Text } = Typography;
const stColor: Record<string, string> = { online: "green", offline: "red", busy: "orange" };
const stName: Record<string, string> = { online: "在线", offline: "离线", busy: "忙碌" };

const NODE_STATUS_OPTIONS = [
  { value: "online", label: "在线" },
  { value: "offline", label: "离线" },
  { value: "busy", label: "忙碌" },
];
const PURPOSE_OPTIONS = [
  { value: "training", label: "训练" },
  { value: "inference", label: "推理" },
  { value: "hybrid", label: "混合" },
];
const DEVICE_STATUS_OPTIONS = [
  { value: "online", label: "在线" },
  { value: "offline", label: "离线" },
];

function heartbeatCell(row: { last_heartbeat?: string | null; heartbeat_stale?: boolean }) {
  if (!row.last_heartbeat) {
    return <Text type="secondary" style={{ fontSize: 12 }}>从未上报</Text>;
  }
  const parsed = parseBackendTime(row.last_heartbeat);
  return (
    <Space direction="vertical" size={0}>
      <Text style={{ fontSize: 12 }}>{parsed ? parsed.toLocaleString() : row.last_heartbeat}</Text>
      {row.heartbeat_stale
        ? <Tag color="orange" style={{ fontSize: 10, lineHeight: "16px", padding: "0 4px", margin: 0 }}>心跳超时</Tag>
        : <Tag color="green" style={{ fontSize: 10, lineHeight: "16px", padding: "0 4px", margin: 0 }}>心跳正常</Tag>}
    </Space>
  );
}

export default function ComputeResourcePage() {
  const [activeTab, setActiveTab] = useState("nodes");
  const [nodes, setNodes] = useState<any[]>([]);
  const [nodeLoading, setNodeLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [purposeFilter, setPurposeFilter] = useState<string | undefined>();
  const [showNodeModal, setShowNodeModal] = useState(false);
  const [editingNode, setEditingNode] = useState<any>(null);
  const [nodeForm] = Form.useForm();

  const [devices, setDevices] = useState<any[]>([]);
  const [deviceLoading, setDeviceLoading] = useState(false);
  const [showDeviceModal, setShowDeviceModal] = useState(false);
  const [editingDevice, setEditingDevice] = useState<any>(null);
  const [deviceForm] = Form.useForm();

  const fetchNodes = useCallback(async () => {
    setNodeLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set("status", statusFilter);
      if (purposeFilter) params.set("purpose", purposeFilter);
      const query = params.toString();
      const res: any = await apiGet("/compute/nodes" + (query ? `?${query}` : ""));
      setNodes(res.items || []);
    } finally {
      setNodeLoading(false);
    }
  }, [statusFilter, purposeFilter]);

  const fetchDevices = useCallback(async () => {
    setDeviceLoading(true);
    try {
      const res: any = await apiGet("/compute/devices");
      setDevices(res.items || []);
    } finally {
      setDeviceLoading(false);
    }
  }, []);

  useEffect(() => { void fetchNodes(); }, [fetchNodes]);
  useEffect(() => { void fetchDevices(); }, [fetchDevices]);

  const reportNodeHeartbeat = async (node: any) => {
    try {
      await apiPost(`/compute/nodes/${node.id}/heartbeat`, {});
      message.success("心跳已上报");
      fetchNodes();
    } catch {
      message.error("心跳上报失败");
    }
  };

  const reportDeviceHeartbeat = async (device: any) => {
    try {
      await apiPost(`/compute/devices/${device.id}/heartbeat`, {});
      message.success("心跳已上报");
      fetchDevices();
    } catch {
      message.error("心跳上报失败");
    }
  };

  const handleNodeSubmit = async (values: any) => {
    if (editingNode) {
      await apiPut("/compute/nodes/" + editingNode.id, values);
      message.success("更新成功");
    } else {
      await apiPost("/compute/nodes", values);
      message.success("创建成功");
    }
    setShowNodeModal(false); setEditingNode(null); nodeForm.resetFields(); fetchNodes();
  };

  const handleNodeDelete = async (id: string) => {
    await apiDelete("/compute/nodes/" + id);
    message.success("删除成功"); fetchNodes();
  };

  const handleDeviceSubmit = async (values: any) => {
    if (editingDevice) {
      await apiPut("/compute/devices/" + editingDevice.id, values);
      message.success("更新成功");
    } else {
      await apiPost("/compute/devices", values);
      message.success("创建成功");
    }
    setShowDeviceModal(false); setEditingDevice(null); deviceForm.resetFields(); fetchDevices();
  };

  const handleDeviceDelete = async (id: string) => {
    await apiDelete("/compute/devices/" + id);
    message.success("删除成功"); fetchDevices();
  };

  const nodeColumns = [
    { title: "节点名称", dataIndex: "name", key: "name",
      render: (t: string) => <Space><CloudServerOutlined />{t}</Space> },
    { title: "编号", dataIndex: "node_number", key: "node_number" },
    { title: "IP地址", dataIndex: "ip_address", key: "ip_address" },
    { title: "类型", dataIndex: "node_type", key: "node_type",
      render: (t: string) => <Tag color={t === "gpu" ? "purple" : "blue"}>{t.toUpperCase()}</Tag> },
    { title: "状态", dataIndex: "status", key: "status",
      render: (s: string) => <Tag color={stColor[s]}>{stName[s] || s}</Tag> },
    { title: "用途", dataIndex: "purpose", key: "purpose",
      render: (p: string) => <Tag>{p === "training" ? "训练" : p === "inference" ? "推理" : "混合"}</Tag> },
    { title: "CPU核", dataIndex: "cpu_cores", key: "cpu_cores" },
    { title: "GPU数", dataIndex: "gpu_count", key: "gpu_count" },
    { title: "内存GB", dataIndex: "memory_gb", key: "memory_gb" },
    { title: "负载", dataIndex: "current_load", key: "current_load",
      render: (v: number) => <Progress percent={Math.round(v || 0)} size="small" /> },
    { title: "最近心跳", key: "last_heartbeat", render: (_: unknown, row: any) => heartbeatCell(row) },
    { title: "操作", key: "actions",
      render: (_: unknown, r: any) => (
        <Space>
          <Button size="small" icon={<EditOutlined />}
            onClick={() => { setEditingNode(r); nodeForm.setFieldsValue(r); setShowNodeModal(true); }}>编辑</Button>
          <Button size="small" icon={<ThunderboltOutlined />} onClick={() => reportNodeHeartbeat(r)}>上报心跳</Button>
          <Popconfirm title="确认删除该节点?" onConfirm={() => handleNodeDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ) },
  ];

  const deviceColumns = [
    { title: "设备名称", dataIndex: "name", key: "name" },
    { title: "分组", dataIndex: "group_id", key: "group_id" },
    { title: "IP地址", dataIndex: "ip_address", key: "ip_address" },
    { title: "类型", dataIndex: "device_type", key: "device_type",
      render: (t: string) => <Tag color="geekblue">{t}</Tag> },
    { title: "状态", dataIndex: "status", key: "status",
      render: (s: string) => <Tag color={stColor[s]}>{stName[s] || s}</Tag> },
    { title: "部署模型", dataIndex: "model_deployed", key: "model_deployed",
      render: (v: string) => v ? <Text code style={{ fontSize: 12 }}>{v}</Text> : <Text type="secondary">-</Text> },
    { title: "版本", dataIndex: "version", key: "version", render: (v: string) => v || "-" },
    { title: "最近心跳", key: "last_heartbeat", render: (_: unknown, row: any) => heartbeatCell(row) },
    { title: "操作", key: "actions",
      render: (_: unknown, r: any) => (
        <Space>
          <Button size="small" icon={<EditOutlined />}
            onClick={() => { setEditingDevice(r); deviceForm.setFieldsValue(r); setShowDeviceModal(true); }}>编辑</Button>
          <Button size="small" icon={<ThunderboltOutlined />} onClick={() => reportDeviceHeartbeat(r)}>上报心跳</Button>
          <Popconfirm title="确认删除该设备?" onConfirm={() => handleDeviceDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ) },
  ];

  return (
    <AppLayout>
      <Card title={<Title level={4}>计算资源管理</Title>}
        extra={<Button icon={<ReloadOutlined />} onClick={() => { fetchNodes(); fetchDevices(); }}>刷新</Button>}>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: "nodes",
              label: "计算节点",
              children: (
                <>
                  <Space wrap style={{ marginBottom: 16 }}>
                    <Select allowClear placeholder="按状态筛选" style={{ minWidth: 120 }}
                      options={NODE_STATUS_OPTIONS} value={statusFilter}
                      onChange={(v) => setStatusFilter(v)} />
                    <Select allowClear placeholder="按用途筛选" style={{ minWidth: 120 }}
                      options={PURPOSE_OPTIONS} value={purposeFilter}
                      onChange={(v) => setPurposeFilter(v)} />
                    <Button type="primary" icon={<PlusOutlined />}
                      onClick={() => { setEditingNode(null); nodeForm.resetFields(); setShowNodeModal(true); }}>新增节点</Button>
                  </Space>
                  <Table dataSource={nodes} columns={nodeColumns} rowKey="id" loading={nodeLoading}
                    size="small" scroll={{ x: 1400 }} />
                </>
              ),
            },
            {
              key: "devices",
              label: "边缘设备",
              children: (
                <>
                  <Space wrap style={{ marginBottom: 16 }}>
                    <Button type="primary" icon={<PlusOutlined />}
                      onClick={() => { setEditingDevice(null); deviceForm.resetFields(); setShowDeviceModal(true); }}>新增设备</Button>
                  </Space>
                  <Table dataSource={devices} columns={deviceColumns} rowKey="id" loading={deviceLoading}
                    size="small" scroll={{ x: 1200 }} />
                </>
              ),
            },
          ]}
        />
      </Card>
      <Modal title={editingNode ? "编辑节点" : "新增节点"} open={showNodeModal}
        onCancel={() => { setShowNodeModal(false); setEditingNode(null); }}
        onOk={() => nodeForm.submit()} width={600}>
        <Form form={nodeForm} layout="vertical" onFinish={handleNodeSubmit} autoComplete="off">
          <Form.Item name="name" label="节点名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="ip_address" label="IP地址"><Input /></Form.Item>
          <Form.Item name="node_type" label="节点类型">
            <Select options={[{ value: "cpu", label: "CPU" }, { value: "gpu", label: "GPU" }]} /></Form.Item>
          <Form.Item name="purpose" label="用途">
            <Select options={PURPOSE_OPTIONS} /></Form.Item>
          <Form.Item name="cpu_cores" label="CPU核数"><Input type="number" /></Form.Item>
          <Form.Item name="gpu_count" label="GPU数量"><Input type="number" /></Form.Item>
          <Form.Item name="memory_gb" label="内存(GB)"><Input type="number" /></Form.Item>
          <Form.Item name="disk_gb" label="磁盘(GB)"><Input type="number" /></Form.Item>
          <Form.Item name="current_load" label="当前负载(%)"><Input type="number" /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>
      <Modal title={editingDevice ? "编辑设备" : "新增设备"} open={showDeviceModal}
        onCancel={() => { setShowDeviceModal(false); setEditingDevice(null); }}
        onOk={() => deviceForm.submit()} width={600}>
        <Form form={deviceForm} layout="vertical" onFinish={handleDeviceSubmit} autoComplete="off">
          <Form.Item name="name" label="设备名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="group_id" label="分组"><Input placeholder="factory-1" /></Form.Item>
          <Form.Item name="ip_address" label="IP地址"><Input /></Form.Item>
          <Form.Item name="device_type" label="设备类型"><Input placeholder="box" /></Form.Item>
          <Form.Item name="status" label="状态" initialValue="online">
            <Select options={DEVICE_STATUS_OPTIONS} /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  );
}
