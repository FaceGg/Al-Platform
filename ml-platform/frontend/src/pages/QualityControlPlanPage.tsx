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
import { createControlPlan, evaluateTightening, listControlPlans, planDiff } from "../api/qms";
import type { QmsControlPlan, QmsPlanDiff } from "../api/qms";
import { useI18n } from "../i18n";

/** 质量管理 · 质量体系 / 动态控制计划（B3-06）：同项目仅一份生效计划（新版生效
 * 旧版归档，双生效被拒）；四因子评估抽样加严，建议乘数走 S1 审批（recipe_change）；
 * 决策流水可复算；相邻版本逐项 diff（E24）。 */

export default function QualityControlPlanPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projects, projectId, setProjectId } = useQualityAlertLookups();
  const [rows, setRows] = useState<QmsControlPlan[]>([]);
  const [detail, setDetail] = useState<QmsControlPlan | null>(null);
  const [diff, setDiff] = useState<QmsPlanDiff | null>(null);
  const [decision, setDecision] = useState<{ suggested_multiplier: number; factors: Record<string, { contribution: number }> } | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [points, setPoints] = useState<{ name: string; sample?: number }[]>([]);
  const [form] = Form.useForm<{ code: string; name?: string; sample?: number }>();
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!projectId) { setRows([]); return; }
    listControlPlans(projectId).then(setRows).catch((e) => message.error(apiErrorText(e)));
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

  const showDiff = async (row: QmsControlPlan) => {
    if (!projectId) return;
    try {
      setDiff(await planDiff(projectId, row.id));
    } catch (e) {
      message.error(apiErrorText(e));
    }
  };

  const evaluate = async (row: QmsControlPlan) => {
    if (!projectId) return;
    try {
      setDecision(await evaluateTightening(projectId, row.id));
    } catch (e) {
      message.error(apiErrorText(e));
    }
  };

  const columns = [
    { title: zh ? "编号" : "Code", dataIndex: "code", key: "code", width: 140 },
    { title: zh ? "版本" : "Version", dataIndex: "version", key: "version", width: 80 },
    {
      title: zh ? "状态" : "Status", dataIndex: "status", key: "status", width: 100,
      render: (value: string) => (value === "active" ? <Tag color="green">{zh ? "生效中" : "Active"}</Tag> : <Tag>{zh ? "已归档" : "Archived"}</Tag>),
    },
    { title: zh ? "乘数" : "Multiplier", dataIndex: "tightening_multiplier", key: "multiplier", width: 90 },
    {
      title: zh ? "质量点" : "Points", key: "points",
      render: (_: unknown, row: QmsControlPlan) => (row.quality_points || []).map((point) => point.name).join("、") || "-",
    },
    {
      title: zh ? "操作" : "Actions", key: "actions", width: 260,
      render: (_: unknown, row: QmsControlPlan) => (
        <Space wrap>
          <Button size="small" onClick={() => { setDetail(row); setDiff(null); setDecision(null); }}>{zh ? "详情" : "Detail"}</Button>
          <Button size="small" onClick={() => void showDiff(row)}>{zh ? "版本 diff" : "Diff"}</Button>
          <Button size="small" type="primary" ghost loading={busy} onClick={() => void evaluate(row)}>
            {zh ? "加严评估" : "Evaluate"}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_control_plans" testId="v2-quality-control-plans">
        <PageHeading
          section="quality"
          navKey="quality_control_plans"
          desc={zh
            ? "动态控制计划：同项目仅一份生效计划，新版生效旧版自动归档（双生效被拒）；四因子（漂移/预警/过程能力/复发）评估抽样加严，建议乘数经 recipe_change 审批单进审批中心；决策流水保留各因子贡献可复算。"
            : "Dynamic control plans with single-active enforcement, four-factor tightening evaluation and version diff."}
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
              <Button type="primary" icon={<PlusOutlined />} data-testid="new-plan"
                onClick={() => { form.resetFields(); setPoints([]); setCreateOpen(true); }}>
                {zh ? "新版计划" : "New version"}
              </Button>
            </Space>
          }
        />
        <Card>
          <Table
            rowKey="id" size="small" columns={columns} dataSource={rows} pagination={false}
            locale={{ emptyText: zh ? "暂无控制计划：点击「新版计划」创建第一版（生效后同项目唯一）" : "No control plans yet" }}
          />
        </Card>

        <Modal open={createOpen} destroyOnClose title={zh ? "新版控制计划" : "New control plan"}
          okText={zh ? "生效" : "Activate"} confirmLoading={busy}
          onCancel={() => setCreateOpen(false)} onOk={() => form.submit()}>
          <Typography.Paragraph type="secondary">
            {zh ? "已有生效计划时创建新版会被拒绝（QMS_PLAN_DUAL_ACTIVE）——先把旧版归档或由审批后的变更流程替换。" : "Only one active plan per project; dual-active is rejected."}
          </Typography.Paragraph>
          <Form form={form} layout="vertical" data-testid="plan-form"
            onFinish={(values) => void run(async () => {
              await createControlPlan(projectId!, { code: values.code.trim(), quality_points: points });
              setCreateOpen(false);
            }, zh ? "计划已生效" : "Plan activated")}>
            <Form.Item name="code" label={zh ? "编号" : "Code"} rules={[{ required: true }]}>
              <Input maxLength={64} placeholder="CP-2026-001" />
            </Form.Item>
            <Typography.Title level={5}>{zh ? "质量点与基础抽样量" : "Quality points"}</Typography.Title>
            <Space.Compact style={{ width: "100%" }}>
              <Form.Item name="name" style={{ marginBottom: 8, flex: 1 }}>
                <Input placeholder={zh ? "质量点名称" : "Point name"} />
              </Form.Item>
              <Form.Item name="sample" style={{ marginBottom: 8, width: 120 }}>
                <InputNumber min={1} placeholder={zh ? "抽样量" : "Sample"} style={{ width: "100%" }} />
              </Form.Item>
              <Button style={{ marginBottom: 8 }}
                onClick={() => {
                  const name: string | undefined = form.getFieldValue("name");
                  if (!name) return;
                  setPoints([...points, { name, sample: form.getFieldValue("sample") }]);
                  form.setFieldValue("name", undefined);
                  form.setFieldValue("sample", undefined);
                }}>
                {zh ? "添加" : "Add"}
              </Button>
            </Space.Compact>
            {points.map((point, index) => (
              <Tag key={index} closable onClose={() => setPoints(points.filter((_, i) => i !== index))}>
                {point.name} · {point.sample ?? "-"}
              </Tag>
            ))}
          </Form>
        </Modal>

        <Modal open={detail !== null} footer={null} onCancel={() => setDetail(null)}
          title={detail ? `${detail.code} v${detail.version}` : ""} width={720}>
          {detail && (
            <>
              <Descriptions size="small" column={2}>
                <Descriptions.Item label={zh ? "状态" : "Status"}>{detail.status}</Descriptions.Item>
                <Descriptions.Item label={zh ? "乘数" : "Multiplier"}>{detail.tightening_multiplier}</Descriptions.Item>
              </Descriptions>
              {diff && (
                <>
                  <Typography.Title level={5} style={{ marginTop: 16 }}>
                    {zh ? `版本 diff：v${diff.from_version} → v${diff.to_version}` : `Diff: v${diff.from_version} → v${diff.to_version}`}
                  </Typography.Title>
                  <Typography.Paragraph style={{ margin: 0 }}>
                    {zh ? "乘数" : "Multiplier"}: {diff.multiplier_before} → {diff.multiplier_after}
                  </Typography.Paragraph>
                  {diff.quality_point_changes.map((change, index) => (
                    <Typography.Paragraph key={index} style={{ margin: 0 }}>
                      <Tag>{change.quality_point}</Tag>
                      <Typography.Text code>{JSON.stringify(change.before)}</Typography.Text>
                      {" → "}
                      <Typography.Text code>{JSON.stringify(change.after)}</Typography.Text>
                    </Typography.Paragraph>
                  ))}
                  {diff.quality_point_changes.length === 0 && (
                    <Typography.Text type="secondary">{zh ? "质量点无变化" : "No point changes"}</Typography.Text>
                  )}
                </>
              )}
              {decision && (
                <>
                  <Typography.Title level={5} style={{ marginTop: 16 }}>
                    {zh ? `加严评估：建议乘数 ${decision.suggested_multiplier}` : `Suggested multiplier: ${decision.suggested_multiplier}`}
                  </Typography.Title>
                  {Object.entries(decision.factors).map(([name, factor]) => (
                    <Typography.Paragraph key={name} style={{ margin: 0 }}>
                      <Tag>{name}</Tag>{zh ? "贡献" : "contribution"}: {factor.contribution}
                    </Typography.Paragraph>
                  ))}
                  <Typography.Text type="secondary">
                    {zh ? "乘数变更须经审批（recipe_change 进审批中心）。" : "Multiplier changes require approval (recipe_change)."}
                  </Typography.Text>
                </>
              )}
            </>
          )}
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
