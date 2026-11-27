import { useCallback, useEffect, useState } from "react";
import {
  App as AntApp, Button, Card, Descriptions, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import { apiErrorText } from "../api/qualityAlerts";
import { createFmea, listControlPlans, listFmeas, syncFmea } from "../api/qms";
import type { QmsFmea, QmsFmeaItem } from "../api/qms";
import { useI18n } from "../i18n";

/** 质量管理 · 质量体系 / FMEA（B3-02）：S/O/D 各 1–10 服务端 clamp，RPN=S×O×D
 * 服务端计算（防前端篡改）；纠正措施一键同步控制计划质量点（生成 recipe_change
 * 待审批变更，接 S1 审批队列）。 */

function rpnColor(rpn: number): string {
  if (rpn >= 200) return "red";
  if (rpn >= 100) return "orange";
  return "green";
}

export default function QualityFmeaPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projects, projectId, setProjectId } = useQualityAlertLookups();
  const [rows, setRows] = useState<QmsFmea[]>([]);
  const [plans, setPlans] = useState<{ id: string; code: string; version: number }[]>([]);
  const [detail, setDetail] = useState<QmsFmea | null>(null);
  const [syncOpen, setSyncOpen] = useState(false);
  const [syncTarget, setSyncTarget] = useState<QmsFmea | null>(null);
  const [planId, setPlanId] = useState<string | undefined>(undefined);
  const [createOpen, setCreateOpen] = useState(false);
  const [items, setItems] = useState<{ failure_mode: string; effect: string; severity: number; occurrence: number; detection: number; prevention: string }[]>([]);
  const [form] = Form.useForm<{
    name: string; failure_mode?: string; effect?: string; severity?: number;
    occurrence?: number; detection?: number; prevention?: string;
  }>();
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!projectId) { setRows([]); setPlans([]); return; }
    listFmeas(projectId).then(setRows).catch((e) => message.error(apiErrorText(e)));
    listControlPlans(projectId).then(setPlans).catch(() => setPlans([]));
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

  const itemColumns = [
    { title: zh ? "失效模式" : "Failure mode", dataIndex: "failure_mode", key: "mode" },
    { title: zh ? "影响" : "Effect", dataIndex: "effect", key: "effect" },
    { title: "S", dataIndex: "severity", key: "s", width: 50 },
    { title: "O", dataIndex: "occurrence", key: "o", width: 50 },
    { title: "D", dataIndex: "detection", key: "d", width: 50 },
    {
      title: "RPN", dataIndex: "rpn", key: "rpn", width: 80,
      render: (value: number) => <Tag color={rpnColor(value)}>{value}</Tag>,
    },
    { title: zh ? "预防措施" : "Prevention", dataIndex: "prevention", key: "prev", ellipsis: true },
  ];

  const columns = [
    { title: zh ? "名称" : "Name", dataIndex: "name", key: "name" },
    { title: zh ? "失效模式数" : "Modes", key: "count", width: 110, render: (_: unknown, row: QmsFmea) => (row.items || []).length },
    {
      title: zh ? "最高 RPN" : "Max RPN", key: "max", width: 100,
      render: (_: unknown, row: QmsFmea) => {
        const max = Math.max(0, ...(row.items || []).map((item) => item.rpn));
        return <Tag color={rpnColor(max)}>{max}</Tag>;
      },
    },
    {
      title: zh ? "操作" : "Actions", key: "actions", width: 200,
      render: (_: unknown, row: QmsFmea) => (
        <Space>
          <Button size="small" onClick={() => setDetail(row)}>{zh ? "详情" : "Detail"}</Button>
          <Button size="small" type="primary" ghost
            onClick={() => { setSyncTarget(row); setPlanId(plans.find((plan) => plan.id)?.id); setSyncOpen(true); }}>
            {zh ? "同步控制计划" : "Sync plan"}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_fmea" testId="v2-quality-fmea">
        <PageHeading
          section="quality"
          navKey="quality_fmea"
          desc={zh
            ? "FMEA：失效模式 / 影响 / S·O·D / 预防措施；S·O·D 各 1–10 由服务端 clamp，RPN 服务端计算（前端传值被忽略）；高 RPN 措施可一键同步控制计划（生成待审批变更进审批中心）。"
            : "FMEA with server-side RPN and control-plan sync via approval."}
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
              <Button type="primary" icon={<PlusOutlined />} data-testid="new-fmea"
                onClick={() => { form.resetFields(); setItems([]); setCreateOpen(true); }}>
                {zh ? "新 FMEA" : "New FMEA"}
              </Button>
            </Space>
          }
        />
        <Card>
          <Table
            rowKey="id" size="small" columns={columns} dataSource={rows} pagination={false}
            locale={{ emptyText: zh ? "暂无 FMEA：点击「新 FMEA」登记失效模式" : "No FMEAs yet" }}
          />
        </Card>

        <Modal open={createOpen} destroyOnClose title={zh ? "新 FMEA" : "New FMEA"} width={720}
          okText={zh ? "创建" : "Create"} confirmLoading={busy}
          onCancel={() => setCreateOpen(false)} onOk={() => form.submit()}>
          <Form form={form} layout="vertical" data-testid="fmea-form"
            onFinish={(values) => void run(async () => {
              await createFmea(projectId!, { name: values.name.trim(), items });
              setCreateOpen(false);
            }, zh ? "FMEA 已创建" : "FMEA created")}>
            <Form.Item name="name" label={zh ? "名称" : "Name"} rules={[{ required: true }]}>
              <Input maxLength={128} />
            </Form.Item>
            <Typography.Title level={5}>{zh ? "失效模式行" : "Failure modes"}</Typography.Title>
            <Space.Compact style={{ width: "100%", marginBottom: 8 }}>
              <Form.Item name="failure_mode" style={{ marginBottom: 4, width: 180 }}>
                <Input placeholder={zh ? "失效模式" : "Mode"} />
              </Form.Item>
              <Form.Item name="effect" style={{ marginBottom: 4, width: 160 }}>
                <Input placeholder={zh ? "影响" : "Effect"} />
              </Form.Item>
              <Form.Item name="severity" style={{ marginBottom: 4, width: 70 }}>
                <InputNumber min={1} max={10} placeholder="S" style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="occurrence" style={{ marginBottom: 4, width: 70 }}>
                <InputNumber min={1} max={10} placeholder="O" style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="detection" style={{ marginBottom: 4, width: 70 }}>
                <InputNumber min={1} max={10} placeholder="D" style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="prevention" style={{ marginBottom: 4, width: 160 }}>
                <Input placeholder={zh ? "预防措施" : "Prevention"} />
              </Form.Item>
              <Button style={{ marginBottom: 4 }}
                onClick={() => {
                  const values = form.getFieldsValue();
                  if (!values.failure_mode) return;
                  setItems([...items, {
                    failure_mode: values.failure_mode, effect: values.effect ?? "",
                    severity: values.severity ?? 1, occurrence: values.occurrence ?? 1,
                    detection: values.detection ?? 1, prevention: values.prevention ?? "",
                  }]);
                  form.resetFields(["failure_mode", "effect", "severity", "occurrence", "detection", "prevention"]);
                }}>
                {zh ? "添加" : "Add"}
              </Button>
            </Space.Compact>
            <Table
              rowKey={(row: QmsFmeaItem) => `${row.failure_mode}-${row.rpn}`} size="small"
              columns={itemColumns} dataSource={items as QmsFmeaItem[]} pagination={false}
              locale={{ emptyText: zh ? "逐行添加失效模式（RPN 由服务端计算）" : "Add failure mode rows" }}
            />
          </Form>
        </Modal>

        <Modal open={syncOpen} destroyOnClose title={zh ? "同步到控制计划" : "Sync to control plan"}
          okText={zh ? "生成审批单" : "Create approval"} confirmLoading={busy}
          onCancel={() => setSyncOpen(false)}
          onOk={() => {
            if (!planId) { message.warning(zh ? "先选择控制计划" : "Select a plan"); return; }
            void run(async () => {
              const result = await syncFmea(projectId!, syncTarget!.id, planId);
              message.info(zh ? `已生成审批单（高 RPN 项 ${result.high_rpn_items} 条）` : `Approval created (${result.high_rpn_items} high-RPN items)`);
              setSyncOpen(false);
            }, zh ? "审批单已生成" : "Approval created");
          }}>
          <Typography.Paragraph type="secondary">
            {zh ? "RPN≥100 的失效模式预防措施将作为 recipe_change 变更进审批中心（批准后落控制计划）。" : "High-RPN preventions become a recipe_change approval."}
          </Typography.Paragraph>
          <Select
            style={{ width: "100%" }} placeholder={zh ? "选择控制计划" : "Select plan"}
            value={planId} onChange={setPlanId}
            options={plans.map((plan) => ({ value: plan.id, label: `${plan.code} v${plan.version}` }))}
          />
          {plans.length === 0 && (
            <Typography.Text type="danger">{zh ? "项目暂无控制计划，请先在「动态控制计划」创建" : "No control plans yet"}</Typography.Text>
          )}
        </Modal>

        <Modal open={detail !== null} footer={null} onCancel={() => setDetail(null)}
          title={detail?.name ?? ""} width={760}>
          {detail && (
            <Table
              rowKey={(row: QmsFmeaItem) => `${row.failure_mode}-${row.rpn}`} size="small"
              columns={itemColumns} dataSource={detail.items || []} pagination={false}
            />
          )}
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
