import { useCallback, useEffect, useMemo, useState } from "react";
import { App as AntApp, Button, Card, Descriptions, Drawer, Empty, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag } from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import apiClient, { formatApiError } from "../api/client";
import { listQualityScenes, listQualitySpecLimits } from "../api/qualityDomain";
import type { QualityFieldRole, QualityScene, QualitySpecLimit } from "../api/qualityDomain";
import { useI18n } from "../i18n";
import { formatLocalTime } from "../utils/time";

/** 质量管理 · 配置 / 场景管理（补齐路线第一批 B1-10，P3）。 */

const FIELD_ROLE_OPTIONS: { value: QualityFieldRole; zh: string; en: string }[] = [
  { value: "sample_key", zh: "样本键", en: "Sample key" },
  { value: "product", zh: "产品", en: "Product" },
  { value: "batch", zh: "批次", en: "Batch" },
  { value: "shift", zh: "班次", en: "Shift" },
  { value: "collected_at", zh: "采集时间", en: "Collected at" },
  { value: "time", zh: "时间列", en: "Time column" },
  { value: "group", zh: "分组列", en: "Group column" },
  { value: "target", zh: "目标列", en: "Target column" },
  { value: "feature", zh: "特征列", en: "Feature column" },
  { value: "ignore", zh: "忽略列", en: "Ignored column" },
  { value: "waveform", zh: "波形列", en: "Waveform column" },
  { value: "condition", zh: "工况列", en: "Condition column" },
];

const STATISTIC_OPTIONS = [
  { value: "value", zh: "值", en: "Value" },
  { value: "mean", zh: "均值", en: "Mean" },
  { value: "min", zh: "最小", en: "Min" },
  { value: "max", zh: "最大", en: "Max" },
  { value: "rms", zh: "RMS", en: "RMS" },
];

interface SceneFormValues {
  code: string;
  name: string;
  description?: string;
  condition_column?: string;
  waveform_column?: string;
}

interface SpecFormValues {
  field: string;
  statistic: QualitySpecLimit["statistic"];
  usl?: number | null;
  lsl?: number | null;
  target?: number | null;
  unit?: string;
}

interface RoleRow {
  role: QualityFieldRole | undefined;
  column: string;
}

export default function QualityScenesPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [scenes, setScenes] = useState<QualityScene[]>([]);
  const [loading, setLoading] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<QualityScene | null>(null);
  const [roleRows, setRoleRows] = useState<RoleRow[]>([]);
  const [form] = Form.useForm<SceneFormValues>();

  // 规格定义抽屉（E27 单一来源）
  const [specScene, setSpecScene] = useState<QualityScene | null>(null);
  const [specs, setSpecs] = useState<QualitySpecLimit[]>([]);
  const [specModalOpen, setSpecModalOpen] = useState(false);
  const [specForm] = Form.useForm<SpecFormValues>();

  useEffect(() => {
    apiClient.get("/projects").then((res) => {
      const items = (res.data?.items || []).map((p: { id: string; name: string }) => ({ id: p.id, name: p.name }));
      setProjects(items);
      if (items.length > 0) setProjectId((current) => current ?? items[0].id);
    }).catch(() => setProjects([]));
  }, []);

  const load = useCallback(() => {
    if (!projectId) { setScenes([]); return; }
    setLoading(true);
    listQualityScenes(projectId).then(setScenes).catch(() => setScenes([])).finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    setEditing(null);
    setRoleRows([]);
    form.setFieldsValue({ code: "", name: "", description: "", condition_column: "", waveform_column: "" });
    setEditorOpen(true);
  };

  const openEdit = (scene: QualityScene) => {
    setEditing(scene);
    const entries = Object.entries(scene.field_roles || {}) as [QualityFieldRole, string][];
    setRoleRows(entries.map(([role, column]) => ({ role, column })));
    form.setFieldsValue({
      code: scene.code,
      name: scene.name,
      description: scene.description || "",
      condition_column: scene.condition_column || "",
      waveform_column: scene.waveform_column || "",
    });
    setEditorOpen(true);
  };

  const submit = async () => {
    if (!projectId) return;
    const values = await form.validateFields();
    const field_roles: Partial<Record<QualityFieldRole, string>> = {};
    for (const row of roleRows) {
      if (row.role && row.column.trim()) field_roles[row.role] = row.column.trim();
    }
    setSaving(true);
    try {
      if (editing) {
        await apiClient.put(`/projects/${projectId}/quality-scenes/${editing.id}`, {
          name: values.name,
          description: values.description || null,
          condition_column: values.condition_column || null,
          waveform_column: values.waveform_column || null,
        });
        await apiClient.put(`/projects/${projectId}/quality-scenes/${editing.id}/field-roles`, { field_roles });
        message.success(zh ? "场景已保存" : "Scene saved");
      } else {
        await apiClient.post(`/projects/${projectId}/quality-scenes`, {
          code: values.code,
          name: values.name,
          description: values.description || null,
          condition_column: values.condition_column || null,
          waveform_column: values.waveform_column || null,
          field_roles,
        });
        message.success(zh ? "场景已创建" : "Scene created");
      }
      setEditorOpen(false);
      load();
    } catch (e) {
      message.error(formatApiError(e, zh ? "保存失败" : "Save failed"));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (scene: QualityScene) => {
    if (!projectId) return;
    try {
      await apiClient.delete(`/projects/${projectId}/quality-scenes/${scene.id}`);
      message.success(zh ? "场景已删除" : "Scene deleted");
      load();
    } catch (e) {
      message.error(formatApiError(e, zh ? "删除失败" : "Delete failed"));
    }
  };

  const openSpecs = async (scene: QualityScene) => {
    setSpecScene(scene);
    if (projectId) {
      const items = await listQualitySpecLimits(projectId, scene.id).catch(() => []);
      setSpecs(items);
    }
  };

  const submitSpec = async () => {
    if (!projectId || !specScene) return;
    const values = await specForm.validateFields();
    try {
      await apiClient.post(`/projects/${projectId}/quality-scenes/${specScene.id}/spec-limits`, {
        field: values.field,
        statistic: values.statistic,
        usl: values.usl ?? null,
        lsl: values.lsl ?? null,
        target: values.target ?? null,
        unit: values.unit || null,
      });
      setSpecs(await listQualitySpecLimits(projectId, specScene.id));
      specForm.resetFields();
      message.success(zh ? "规格已保存" : "Spec saved");
    } catch (e) {
      message.error(formatApiError(e, zh ? "规格保存失败" : "Spec save failed"));
    }
  };

  const removeSpec = async (spec: QualitySpecLimit) => {
    if (!projectId || !specScene) return;
    try {
      await apiClient.delete(`/projects/${projectId}/quality-scenes/${specScene.id}/spec-limits/${spec.id}`);
      setSpecs(await listQualitySpecLimits(projectId, specScene.id));
    } catch (e) {
      message.error(formatApiError(e, zh ? "删除失败" : "Delete failed"));
    }
  };

  const roleLabel = useMemo(() => {
    const map: Record<string, { zh: string; en: string }> = {};
    for (const option of FIELD_ROLE_OPTIONS) map[option.value] = { zh: option.zh, en: option.en };
    return map;
  }, []);

  const columns = [
    { title: zh ? "编码" : "Code", dataIndex: "code", key: "code" },
    { title: zh ? "名称" : "Name", dataIndex: "name", key: "name" },
    {
      title: zh ? "字段角色" : "Field roles", key: "roles",
      render: (_: unknown, scene: QualityScene) => {
        const entries = Object.entries(scene.field_roles || {});
        if (entries.length === 0) return <Tag>{zh ? "未配置" : "Not configured"}</Tag>;
        return (
          <Space wrap size={4}>
            {entries.map(([role, column]) => (
              <Tag key={role}>{roleLabel[role]?.[zh ? "zh" : "en"] || role}: {column}</Tag>
            ))}
          </Space>
        );
      },
    },
    {
      title: zh ? "工况列" : "Condition column", dataIndex: "condition_column", key: "condition_column",
      render: (value: string | null) => value || "-",
    },
    {
      title: zh ? "更新时间" : "Updated", dataIndex: "updated_at", key: "updated_at",
      render: (value: string | null) => (value ? formatLocalTime(value) : "-"),
    },
    {
      title: zh ? "操作" : "Actions", key: "actions",
      render: (_: unknown, scene: QualityScene) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(scene)}>{zh ? "编辑" : "Edit"}</Button>
          <Button size="small" onClick={() => openSpecs(scene)}>{zh ? "规格" : "Specs"}</Button>
          <Popconfirm
            title={zh ? "删除该场景？" : "Delete this scene?"}
            description={zh ? "场景下工位与规格一并删除。" : "Stations and specs under the scene are removed as well."}
            onConfirm={() => remove(scene)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_scenes" testId="v2-quality-scenes">
        <PageHeading
          section="quality"
          navKey="quality_scenes"
          desc={zh ? "项目 → 场景 → 工位 → 设备的领域模型入口：字段角色与规格定义在此维护。" : "Domain entry for project → scene → station → device: field roles and spec limits live here."}
          actions={
            <Space>
              <Select
                aria-label={zh ? "选择项目" : "Select project"}
                style={{ minWidth: 200 }}
                placeholder={zh ? "选择项目" : "Select project"}
                value={projectId ?? undefined}
                onChange={(value: string) => setProjectId(value)}
                options={projects.map((p) => ({ value: p.id, label: p.name }))}
              />
              <Button icon={<ReloadOutlined />} onClick={load}>{zh ? "刷新" : "Refresh"}</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} disabled={!projectId}>
                {zh ? "新建场景" : "New scene"}
              </Button>
            </Space>
          }
        />
        <Card>
          <Table
            rowKey="id"
            loading={loading}
            columns={columns}
            dataSource={scenes}
            pagination={false}
            locale={{ emptyText: <Empty description={zh ? "暂无场景，点击右上角「新建场景」创建" : "No scenes yet; create one from the toolbar"} /> }}
          />
        </Card>

        <Modal
          title={editing ? (zh ? `编辑场景：${editing.name}` : `Edit scene: ${editing.name}`) : zh ? "新建场景" : "New scene"}
          open={editorOpen}
          onCancel={() => setEditorOpen(false)}
          onOk={submit}
          confirmLoading={saving}
          width={720}
          okText={zh ? "保存" : "Save"}
        >
          <Form form={form} layout="vertical">
            <Form.Item name="code" label={zh ? "编码" : "Code"} rules={[{ required: !editing, message: zh ? "请输入场景编码" : "Code required" }]}>
              <Input maxLength={64} disabled={Boolean(editing)} placeholder={zh ? "项目内唯一，如 welding-cell-a" : "Unique per project"} />
            </Form.Item>
            <Form.Item name="name" label={zh ? "名称" : "Name"} rules={[{ required: true, message: zh ? "请输入名称" : "Name required" }]}>
              <Input maxLength={128} />
            </Form.Item>
            <Form.Item name="description" label={zh ? "描述" : "Description"}>
              <Input.TextArea rows={2} maxLength={4000} />
            </Form.Item>
            <Form.Item
              name="condition_column"
              label={zh ? "工况列（路由键）" : "Condition column"}
              extra={zh ? "绑定部署时须与部署声明的工况列一致。" : "Must match the bound deployment's condition column."}
            >
              <Input maxLength={128} />
            </Form.Item>
            <Form.Item name="waveform_column" label={zh ? "波形列（可选）" : "Waveform column"}>
              <Input maxLength={256} />
            </Form.Item>
            <div>
              <Space style={{ marginBottom: 8 }}>
                <strong>{zh ? "字段角色" : "Field roles"}</strong>
                <Button size="small" icon={<PlusOutlined />} onClick={() => setRoleRows((rows) => [...rows, { role: undefined, column: "" }])}>
                  {zh ? "添加角色" : "Add role"}
                </Button>
              </Space>
              {roleRows.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={zh ? "未配置角色；样本键/批次/工况等占用列训练时自动排除" : "No roles configured"} />
              ) : (
                roleRows.map((row, index) => (
                  <Space key={index} style={{ display: "flex", marginBottom: 8 }} align="baseline">
                    <Select
                      aria-label={zh ? "角色" : "Role"}
                      style={{ width: 180 }}
                      placeholder={zh ? "选择角色" : "Role"}
                      value={row.role}
                      onChange={(value: QualityFieldRole) => setRoleRows((rows) => rows.map((r, i) => (i === index ? { ...r, role: value } : r)))}
                      options={FIELD_ROLE_OPTIONS.map((option) => ({ value: option.value, label: zh ? option.zh : option.en }))}
                    />
                    <Input
                      aria-label={zh ? "列名" : "Column"}
                      style={{ width: 260 }}
                      maxLength={256}
                      placeholder={zh ? "列名" : "Column name"}
                      value={row.column}
                      onChange={(event) => setRoleRows((rows) => rows.map((r, i) => (i === index ? { ...r, column: event.target.value } : r)))}
                    />
                    <Button size="small" danger icon={<DeleteOutlined />} onClick={() => setRoleRows((rows) => rows.filter((_, i) => i !== index))} />
                  </Space>
                ))
              )}
            </div>
          </Form>
        </Modal>

        <Drawer
          title={specScene ? (zh ? `规格定义：${specScene.name}` : `Spec limits: ${specScene.name}`) : ""}
          open={specScene !== null}
          onClose={() => setSpecScene(null)}
          width={560}
        >
          <Card size="small" style={{ marginBottom: 16 }}>
            <Form form={specForm} layout="inline" initialValues={{ statistic: "value" }}>
              <Form.Item name="field" label={zh ? "字段" : "Field"} rules={[{ required: true }]}>
                <Input maxLength={256} style={{ width: 140 }} />
              </Form.Item>
              <Form.Item name="statistic" label={zh ? "统计量" : "Statistic"}>
                <Select style={{ width: 90 }} options={STATISTIC_OPTIONS.map((o) => ({ value: o.value, label: zh ? o.zh : o.en }))} />
              </Form.Item>
              <Form.Item name="usl" label="USL">
                <Input style={{ width: 80 }} />
              </Form.Item>
              <Form.Item name="lsl" label="LSL">
                <Input style={{ width: 80 }} />
              </Form.Item>
              <Form.Item name="target" label={zh ? "目标值" : "Target"}>
                <Input style={{ width: 80 }} />
              </Form.Item>
              <Form.Item name="unit" label={zh ? "单位" : "Unit"}>
                <Input maxLength={32} style={{ width: 70 }} />
              </Form.Item>
              <Button type="primary" onClick={submitSpec}>{zh ? "添加" : "Add"}</Button>
            </Form>
          </Card>
          {specs.length === 0 ? (
            <Empty description={zh ? "暂无规格；判据引擎与能力指数（后续批次）从这里取数" : "No specs yet"} />
          ) : (
            <Descriptions column={1} bordered size="small">
              {specs.map((spec) => (
                <Descriptions.Item
                  key={spec.id}
                  label={`${spec.field} · ${STATISTIC_OPTIONS.find((o) => o.value === spec.statistic)?.[zh ? "zh" : "en"] || spec.statistic}`}
                >
                  <Space wrap size={4}>
                    {spec.usl != null && <Tag>USL {spec.usl}</Tag>}
                    {spec.lsl != null && <Tag>LSL {spec.lsl}</Tag>}
                    {spec.target != null && <Tag>{zh ? "目标" : "TGT"} {spec.target}</Tag>}
                    {spec.unit && <Tag>{spec.unit}</Tag>}
                    <Button size="small" danger icon={<DeleteOutlined />} onClick={() => removeSpec(spec)} />
                  </Space>
                </Descriptions.Item>
              ))}
            </Descriptions>
          )}
        </Drawer>
      </V2PageFrame>
    </AppLayout>
  );
}
