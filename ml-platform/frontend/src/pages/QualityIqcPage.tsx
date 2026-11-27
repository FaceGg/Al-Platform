import { useCallback, useEffect, useState } from "react";
import {
  App as AntApp, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import { apiErrorText } from "../api/qualityAlerts";
import {
  createIqcRecord, createSupplier, disableSupplier,
  listIqcRecords, listScars, listSuppliers,
} from "../api/qms";
import type { QmsIqcRecord, QmsScar, QmsSupplier } from "../api/qms";
import { useI18n } from "../i18n";

/** 质量管理 · 质量体系 / 来料检验与 SCAR（B3-05）：数量约束校验（检验数≤来料数、
 * 不良数≤检验数）；检验不合格自动生成唯一 SCAR（一检验一 SCAR）；停用供应商
 * 新来料被拒。 */

export default function QualityIqcPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projects, projectId, setProjectId } = useQualityAlertLookups();
  const [suppliers, setSuppliers] = useState<QmsSupplier[]>([]);
  const [iqcRows, setIqcRows] = useState<QmsIqcRecord[]>([]);
  const [scars, setScars] = useState<QmsScar[]>([]);
  const [supplierOpen, setSupplierOpen] = useState(false);
  const [iqcOpen, setIqcOpen] = useState(false);
  const [supplierForm] = Form.useForm<{ code: string; name: string }>();
  const [iqcForm] = Form.useForm<{ supplier_id: string; arrival_count: number; inspected_count: number; defect_count: number }>();
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!projectId) { setSuppliers([]); setIqcRows([]); setScars([]); return; }
    listSuppliers(projectId).then(setSuppliers).catch((e) => message.error(apiErrorText(e)));
    listIqcRecords(projectId).then(setIqcRows).catch(() => setIqcRows([]));
    listScars(projectId).then(setScars).catch(() => setScars([]));
  }, [projectId, message]);

  useEffect(() => { load(); }, [load]);

  const run = async (operation: () => Promise<unknown>, successText: string) => {
    setBusy(true);
    try {
      await operation();
      message.success(successText);
      load();
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const supplierName = (id: string) => suppliers.find((item) => item.id === id)?.name ?? id.slice(0, 8);

  const supplierColumns = [
    { title: zh ? "代码" : "Code", dataIndex: "code", key: "code", width: 120 },
    { title: zh ? "名称" : "Name", dataIndex: "name", key: "name" },
    {
      title: zh ? "状态" : "Status", dataIndex: "status", key: "status", width: 100,
      render: (value: string) => (value === "active" ? <Tag color="green">{zh ? "合作中" : "Active"}</Tag> : <Tag color="red">{zh ? "已停用" : "Disabled"}</Tag>),
    },
    {
      title: zh ? "操作" : "Actions", key: "actions", width: 120,
      render: (_: unknown, row: QmsSupplier) => (
        row.status === "active" ? (
          <Button size="small" danger loading={busy}
            onClick={() => void run(() => disableSupplier(projectId!, row.id), zh ? "已停用" : "Disabled")}>
            {zh ? "停用" : "Disable"}
          </Button>
        ) : null
      ),
    },
  ];

  const iqcColumns = [
    {
      title: zh ? "供应商" : "Supplier", dataIndex: "supplier_id", key: "supplier",
      render: (value: string) => supplierName(value),
    },
    { title: zh ? "来料数" : "Arrival", dataIndex: "arrival_count", key: "arrival", width: 90 },
    { title: zh ? "检验数" : "Inspected", dataIndex: "inspected_count", key: "inspected", width: 90 },
    { title: zh ? "不良数" : "Defects", dataIndex: "defect_count", key: "defects", width: 90 },
    {
      title: "SCAR", dataIndex: "scar_id", key: "scar", width: 120,
      render: (value: string | null) => (value ? <Tag color="red">SCAR</Tag> : "-"),
    },
  ];

  const scarColumns = [
    { title: "IQC ID", dataIndex: "iqc_record_id", key: "iqc", ellipsis: true },
    { title: zh ? "原因" : "Cause", dataIndex: "cause", key: "cause", ellipsis: true, render: (v: string | null) => v ?? "-" },
    {
      title: zh ? "关闭时间" : "Closed", dataIndex: "closed_at", key: "closed", width: 170,
      render: (value: string | null) => value ?? <Tag color="orange">{zh ? "未关闭" : "Open"}</Tag>,
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_iqc" testId="v2-quality-iqc">
        <PageHeading
          section="quality"
          navKey="quality_iqc"
          desc={zh
            ? "来料检验（IQC）与供应商整改请求（SCAR）：数量约束校验（检验数≤来料数、不良数≤检验数）；检验不合格自动生成唯一 SCAR（一检验一 SCAR）；停用供应商的新来料被拒。"
            : "Incoming inspection with count constraints and one-SCAR-per-IQC uniqueness."}
          actions={
            <Space>
              <Select
                aria-label={zh ? "选择项目" : "Select project"}
                style={{ minWidth: 180 }}
                placeholder={zh ? "选择项目" : "Select project"}
                value={projectId ?? undefined}
                onChange={(value: string) => setProjectId(value)}
                options={projects.map((item) => ({ value: item.id, label: item.name }))}
              />
              <Button icon={<PlusOutlined />} data-testid="new-supplier"
                onClick={() => { supplierForm.resetFields(); setSupplierOpen(true); }}>
                {zh ? "供应商" : "Supplier"}
              </Button>
              <Button type="primary" icon={<PlusOutlined />} data-testid="new-iqc"
                onClick={() => { iqcForm.resetFields(); setIqcOpen(true); }}>
                {zh ? "来料检验" : "IQC record"}
              </Button>
            </Space>
          }
        />
        <Card title={zh ? "供应商台账" : "Suppliers"}>
          <Table
            rowKey="id" size="small" columns={supplierColumns} dataSource={suppliers} pagination={false}
            locale={{ emptyText: zh ? "暂无供应商：点击「供应商」登记第一家" : "No suppliers yet" }}
          />
        </Card>
        <Card title={zh ? "来料检验记录" : "IQC records"} style={{ marginTop: 16 }}>
          <Table
            rowKey="id" size="small" columns={iqcColumns} dataSource={iqcRows} pagination={false}
            locale={{ emptyText: zh ? "暂无检验记录：点击「来料检验」登记（不良自动生成 SCAR）" : "No IQC records yet" }}
          />
        </Card>
        <Card title={zh ? "SCAR 台账" : "SCARs"} style={{ marginTop: 16 }}>
          <Table
            rowKey="id" size="small" columns={scarColumns} dataSource={scars} pagination={false}
            locale={{ emptyText: zh ? "暂无 SCAR：检验不合格自动生成" : "No SCARs yet" }}
          />
        </Card>

        <Modal open={supplierOpen} destroyOnClose title={zh ? "登记供应商" : "New supplier"}
          okText={zh ? "创建" : "Create"} confirmLoading={busy}
          onCancel={() => setSupplierOpen(false)} onOk={() => supplierForm.submit()}>
          <Form form={supplierForm} layout="vertical" data-testid="supplier-form"
            onFinish={(values) => void run(async () => {
              await createSupplier(projectId!, { code: values.code.trim(), name: values.name.trim() });
              setSupplierOpen(false);
            }, zh ? "供应商已登记" : "Supplier created")}>
            <Form.Item name="code" label={zh ? "代码" : "Code"} rules={[{ required: true }]}>
              <Input maxLength={64} placeholder="SUP-001" />
            </Form.Item>
            <Form.Item name="name" label={zh ? "名称" : "Name"} rules={[{ required: true }]}>
              <Input maxLength={128} />
            </Form.Item>
          </Form>
        </Modal>

        <Modal open={iqcOpen} destroyOnClose title={zh ? "来料检验登记" : "New IQC record"}
          okText={zh ? "登记" : "Record"} confirmLoading={busy}
          onCancel={() => setIqcOpen(false)} onOk={() => iqcForm.submit()}>
          <Form form={iqcForm} layout="vertical" data-testid="iqc-form"
            onFinish={(values) => void run(async () => {
              const result = await createIqcRecord(projectId!, {
                supplier_id: values.supplier_id,
                arrival_count: values.arrival_count,
                inspected_count: values.inspected_count,
                defect_count: values.defect_count,
              });
              if (result.scar_id) message.info(zh ? "检验不合格：已自动生成 SCAR" : "SCAR auto-created");
              setIqcOpen(false);
            }, zh ? "检验记录已登记" : "IQC recorded")}>
            <Form.Item name="supplier_id" label={zh ? "供应商" : "Supplier"} rules={[{ required: true }]}>
              <Select options={suppliers.filter((item) => item.status === "active").map((item) => ({ value: item.id, label: `${item.name}（${item.code}）` }))} />
            </Form.Item>
            <Space size="large">
              <Form.Item name="arrival_count" label={zh ? "来料数" : "Arrival"} rules={[{ required: true }]}>
                <InputNumber min={0} style={{ width: 140 }} />
              </Form.Item>
              <Form.Item name="inspected_count" label={zh ? "检验数" : "Inspected"} rules={[{ required: true }]}
                extra={zh ? "须 ≤ 来料数" : "≤ arrival"}>
                <InputNumber min={0} style={{ width: 140 }} />
              </Form.Item>
              <Form.Item name="defect_count" label={zh ? "不良数" : "Defects"} rules={[{ required: true }]}
                extra={zh ? "须 ≤ 检验数" : "≤ inspected"}>
                <InputNumber min={0} style={{ width: 140 }} />
              </Form.Item>
            </Space>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              {zh ? "违反数量约束返回 IQC_COUNT_CONSTRAINT；停用供应商返回 SUPPLIER_DISABLED。" : "Count constraints are enforced server-side."}
            </Typography.Paragraph>
          </Form>
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
