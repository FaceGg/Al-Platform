import { useCallback, useEffect, useState } from "react";
import { App as AntApp, Button, Card, Empty, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Tooltip } from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import apiClient, { formatApiError } from "../api/client";
import { listQualityScenes, listQualityStations } from "../api/qualityDomain";
import type { QualityScene, QualityStation } from "../api/qualityDomain";
import { useI18n } from "../i18n";

/**
 * 质量管理 · 配置 / 工位与设备（B1-10，P3）。
 * 设备复用既有 /api/compute/devices（更正 C15）：注册/编辑内嵌表单，
 * 心跳超时（默认 180s）显示离线；影子两列为 B4-02 预留，空态展示。
 */

const HEARTBEAT_STALE_SECONDS = 180;

interface EdgeDeviceView {
  id: string;
  name: string;
  status?: string;
  device_type?: string;
  ip_address?: string;
  last_heartbeat?: string | null;
  owner_id?: string;
}

interface StationFormValues {
  code: string;
  name: string;
  description?: string;
  scene_id: string;
  factory?: string;
  workshop?: string;
  production_line?: string;
  edge_device_id?: string | null;
}

interface DeviceFormValues {
  name: string;
  device_type?: string;
  ip_address?: string;
}

export default function QualityStationsPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [scenes, setScenes] = useState<QualityScene[]>([]);
  const [sceneId, setSceneId] = useState<string | null>(null);
  const [stations, setStations] = useState<QualityStation[]>([]);
  const [devices, setDevices] = useState<EdgeDeviceView[]>([]);
  const [currentUserId, setCurrentUserId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [stationOpen, setStationOpen] = useState(false);
  const [editingStation, setEditingStation] = useState<QualityStation | null>(null);
  const [saving, setSaving] = useState(false);
  const [deviceOpen, setDeviceOpen] = useState(false);
  const [deviceForm] = Form.useForm<DeviceFormValues>();
  const [stationForm] = Form.useForm<StationFormValues>();

  useEffect(() => {
    apiClient.get("/projects").then((res) => {
      const items = (res.data?.items || []).map((p: { id: string; name: string }) => ({ id: p.id, name: p.name }));
      setProjects(items);
      if (items.length > 0) setProjectId((current) => current ?? items[0].id);
    }).catch(() => setProjects([]));
    apiClient.get("/auth/me").then((res) => setCurrentUserId(String(res.data?.id || ""))).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!projectId) { setScenes([]); setSceneId(null); return; }
    listQualityScenes(projectId).then((items) => {
      setScenes(items);
      setSceneId((current) => (current && items.some((s) => s.id === current) ? current : items[0]?.id ?? null));
    }).catch(() => setScenes([]));
  }, [projectId]);

  const load = useCallback(() => {
    if (!projectId) { setStations([]); return; }
    setLoading(true);
    listQualityStations(projectId, sceneId ?? undefined).then(setStations).catch(() => setStations([])).finally(() => setLoading(false));
  }, [projectId, sceneId]);

  useEffect(() => { load(); }, [load]);

  const loadDevices = useCallback(() => {
    apiClient.get("/compute/devices").then((res) => {
      setDevices(Array.isArray(res.data) ? res.data : (res.data?.items || []));
    }).catch(() => setDevices([]));
  }, []);

  useEffect(() => { loadDevices(); }, [loadDevices]);

  const deviceById = useCallback(
    (id: string | null | undefined) => (id ? devices.find((device) => device.id === id) : undefined),
    [devices],
  );

  const deviceStatus = (device: EdgeDeviceView | undefined): { label: string; color: string } => {
    if (!device) return { label: zh ? "未绑定" : "Unbound", color: "default" };
    const heartbeat = device.last_heartbeat ? new Date(device.last_heartbeat.endsWith("Z") ? device.last_heartbeat : `${device.last_heartbeat}Z`).getTime() : 0;
    const stale = !heartbeat || Date.now() - heartbeat > HEARTBEAT_STALE_SECONDS * 1000;
    if (stale) return { label: zh ? "离线" : "Offline", color: "error" };
    return { label: zh ? "在线" : "Online", color: "success" };
  };

  const openStation = (station: QualityStation | null) => {
    setEditingStation(station);
    stationForm.setFieldsValue(station ? {
      code: station.code,
      name: station.name,
      description: station.description || "",
      scene_id: station.scene_id,
      factory: station.factory || "",
      workshop: station.workshop || "",
      production_line: station.production_line || "",
      edge_device_id: station.edge_device_id,
    } : {
      code: "", name: "", description: "", scene_id: sceneId ?? undefined,
      factory: "", workshop: "", production_line: "", edge_device_id: null,
    });
    setStationOpen(true);
  };

  const submitStation = async () => {
    if (!projectId) return;
    const values = await stationForm.validateFields();
    setSaving(true);
    try {
      if (editingStation) {
        await apiClient.put(`/projects/${projectId}/quality-stations/${editingStation.id}`, {
          name: values.name,
          description: values.description || null,
          factory: values.factory || null,
          workshop: values.workshop || null,
          production_line: values.production_line || null,
          edge_device_id: values.edge_device_id || null,
        });
        message.success(zh ? "工位已保存" : "Station saved");
      } else {
        await apiClient.post(`/projects/${projectId}/quality-stations`, {
          code: values.code,
          name: values.name,
          description: values.description || null,
          scene_id: values.scene_id,
          factory: values.factory || null,
          workshop: values.workshop || null,
          production_line: values.production_line || null,
          edge_device_id: values.edge_device_id || null,
          enabled: true,
        });
        message.success(zh ? "工位已创建" : "Station created");
      }
      setStationOpen(false);
      load();
    } catch (e) {
      message.error(formatApiError(e, zh ? "保存失败" : "Save failed"));
    } finally {
      setSaving(false);
    }
  };

  const removeStation = async (station: QualityStation) => {
    if (!projectId) return;
    try {
      await apiClient.delete(`/projects/${projectId}/quality-stations/${station.id}`);
      message.success(zh ? "工位已删除" : "Station deleted");
      load();
    } catch (e) {
      message.error(formatApiError(e, zh ? "删除失败" : "Delete failed"));
    }
  };

  const submitDevice = async () => {
    const values = await deviceForm.validateFields();
    try {
      await apiClient.post("/compute/devices", {
        name: values.name,
        device_type: values.device_type || "box",
        ip_address: values.ip_address || "",
      });
      message.success(zh ? "设备已注册" : "Device registered");
      setDeviceOpen(false);
      deviceForm.resetFields();
      loadDevices();
    } catch (e) {
      message.error(formatApiError(e, zh ? "设备注册失败" : "Device registration failed"));
    }
  };

  const columns = [
    { title: zh ? "编码" : "Code", dataIndex: "code", key: "code" },
    { title: zh ? "名称" : "Name", dataIndex: "name", key: "name" },
    {
      title: zh ? "归属（工厂/车间/产线）" : "Factory / Workshop / Line", key: "location",
      render: (_: unknown, station: QualityStation) =>
        [station.factory, station.workshop, station.production_line].filter(Boolean).join(" / ") || "-",
    },
    {
      title: zh ? "绑定设备" : "Device", key: "device",
      render: (_: unknown, station: QualityStation) => {
        const device = deviceById(station.edge_device_id);
        const status = deviceStatus(device);
        return (
          <Space size={4}>
            <span>{device?.name || "-"}</span>
            {device && <Tag color={status.color}>{status.label}</Tag>}
          </Space>
        );
      },
    },
    {
      title: zh ? "影子状态" : "Shadow", key: "shadow",
      render: () => <Tooltip title={zh ? "设备影子（desired/reported）随边缘批次（B4-02）启用" : "Device shadow (desired/reported) lands with the edge batch (B4-02)"}><Tag>{zh ? "未启用" : "Not enabled"}</Tag></Tooltip>,
    },
    { title: zh ? "启用" : "Enabled", dataIndex: "enabled", key: "enabled", render: (value: boolean) => (value ? <Tag color="success">{zh ? "启用" : "On"}</Tag> : <Tag>{zh ? "停用" : "Off"}</Tag>) },
    {
      title: zh ? "操作" : "Actions", key: "actions",
      render: (_: unknown, station: QualityStation) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openStation(station)}>{zh ? "编辑" : "Edit"}</Button>
          <Popconfirm title={zh ? "删除该工位？" : "Delete this station?"} onConfirm={() => removeStation(station)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const ownableDevices = devices.filter((device) => !device.owner_id || !currentUserId || device.owner_id === currentUserId);

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_stations" testId="v2-quality-stations">
        <PageHeading
          section="quality"
          navKey="quality_stations"
          desc={zh ? "工位台账与边缘设备绑定：工厂/车间/产线归属供驾驶舱四级联动（后续批次）消费。" : "Station registry and edge device binding; location fields feed the cockpit four-level scope (later batch)."}
          actions={
            <Space>
              <Select
                aria-label={zh ? "选择项目" : "Select project"}
                style={{ minWidth: 180 }}
                placeholder={zh ? "选择项目" : "Select project"}
                value={projectId ?? undefined}
                onChange={(value: string) => setProjectId(value)}
                options={projects.map((p) => ({ value: p.id, label: p.name }))}
              />
              <Select
                aria-label={zh ? "筛选场景" : "Filter scene"}
                style={{ minWidth: 180 }}
                allowClear
                placeholder={zh ? "全部场景" : "All scenes"}
                value={sceneId ?? undefined}
                onChange={(value: string | undefined) => setSceneId(value ?? null)}
                options={scenes.map((s) => ({ value: s.id, label: `${s.name}（${s.code}）` }))}
              />
              <Button icon={<ReloadOutlined />} onClick={() => { load(); loadDevices(); }}>{zh ? "刷新" : "Refresh"}</Button>
              <Button onClick={() => setDeviceOpen(true)} disabled={!projectId}>{zh ? "注册设备" : "Register device"}</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openStation(null)} disabled={!projectId || !sceneId}>
                {zh ? "新建工位" : "New station"}
              </Button>
            </Space>
          }
        />
        <Card>
          <Table
            rowKey="id"
            loading={loading}
            columns={columns}
            dataSource={stations}
            pagination={false}
            locale={{ emptyText: <Empty description={zh ? "暂无工位；先建场景，再新建工位并绑定设备" : "No stations yet"} /> }}
          />
        </Card>

        <Modal
          title={editingStation ? (zh ? `编辑工位：${editingStation.name}` : `Edit station: ${editingStation.name}`) : zh ? "新建工位" : "New station"}
          open={stationOpen}
          onCancel={() => setStationOpen(false)}
          onOk={submitStation}
          confirmLoading={saving}
          okText={zh ? "保存" : "Save"}
        >
          <Form form={stationForm} layout="vertical">
            <Form.Item name="code" label={zh ? "编码" : "Code"} rules={[{ required: !editingStation, message: zh ? "请输入工位编码" : "Code required" }]}>
              <Input maxLength={64} disabled={Boolean(editingStation)} placeholder={zh ? "场景内唯一，如 st-01" : "Unique per scene"} />
            </Form.Item>
            <Form.Item name="name" label={zh ? "名称" : "Name"} rules={[{ required: true, message: zh ? "请输入名称" : "Name required" }]}>
              <Input maxLength={128} />
            </Form.Item>
            <Form.Item name="scene_id" label={zh ? "所属场景" : "Scene"} rules={[{ required: true }]}>
              <Select disabled={Boolean(editingStation)} options={scenes.map((s) => ({ value: s.id, label: `${s.name}（${s.code}）` }))} />
            </Form.Item>
            <Space style={{ display: "flex" }} size={12}>
              <Form.Item name="factory" label={zh ? "工厂" : "Factory"}>
                <Input maxLength={128} style={{ width: 140 }} />
              </Form.Item>
              <Form.Item name="workshop" label={zh ? "车间" : "Workshop"}>
                <Input maxLength={128} style={{ width: 140 }} />
              </Form.Item>
              <Form.Item name="production_line" label={zh ? "产线" : "Line"}>
                <Input maxLength={128} style={{ width: 140 }} />
              </Form.Item>
            </Space>
            <Form.Item
              name="edge_device_id"
              label={zh ? "绑定边缘设备" : "Edge device"}
              extra={zh ? "设备属于当前用户才可绑定（跨成员共享随治理批次收敛）。" : "Only devices owned by the current user can be bound."}
            >
              <Select
                allowClear
                placeholder={zh ? "选择设备" : "Select device"}
                options={ownableDevices.map((device) => ({ value: device.id, label: device.name }))}
              />
            </Form.Item>
            <Form.Item name="description" label={zh ? "描述" : "Description"}>
              <Input.TextArea rows={2} maxLength={4000} />
            </Form.Item>
          </Form>
        </Modal>

        <Modal
          title={zh ? "注册边缘设备" : "Register edge device"}
          open={deviceOpen}
          onCancel={() => setDeviceOpen(false)}
          onOk={submitDevice}
          okText={zh ? "注册" : "Register"}
        >
          <Form form={deviceForm} layout="vertical">
            <Form.Item name="name" label={zh ? "设备名" : "Name"} rules={[{ required: true, message: zh ? "请输入设备名" : "Name required" }]}>
              <Input maxLength={128} />
            </Form.Item>
            <Form.Item name="device_type" label={zh ? "类型" : "Type"} initialValue="box">
              <Input maxLength={64} />
            </Form.Item>
            <Form.Item name="ip_address" label="IP">
              <Input maxLength={64} />
            </Form.Item>
          </Form>
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
