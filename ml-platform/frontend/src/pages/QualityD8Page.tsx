import { useCallback, useEffect, useState } from "react";
import {
  App as AntApp, Button, Card, Descriptions, Form, Input, Modal, Select, Space, Table, Tag, Typography,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import { apiErrorText } from "../api/qualityAlerts";
import { advanceD8, closeD8, createD8, draftD8, exportD8Evidence, getD8, listD8 } from "../api/qms";
import type { QmsD8, QmsD8Detail } from "../api/qms";
import { useI18n } from "../i18n";

/** 质量管理 · 质量体系 / 8D 报告（B3-03）：D0–D8 顺序推进、D6 未通过不得结案、
 * LLM 起草 D1–D5 初稿（自动入动作审计）、证据包导出（8D 口径待质量专家评审）。 */

export default function QualityD8Page() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projects, projectId, setProjectId } = useQualityAlertLookups();
  const [rows, setRows] = useState<QmsD8[]>([]);
  const [detail, setDetail] = useState<QmsD8Detail | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [draftOpen, setDraftOpen] = useState(false);
  const [draftTarget, setDraftTarget] = useState<QmsD8 | null>(null);
  const [form] = Form.useForm<{ code: string; title: string; ncr_id?: string }>();
  const [draftForm] = Form.useForm<{ context: string }>();
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!projectId) { setRows([]); return; }
    listD8(projectId).then(setRows).catch((e) => message.error(apiErrorText(e)));
  }, [projectId, message]);

  useEffect(() => { load(); }, [load]);

  const run = async (operation: () => Promise<unknown>, successText: string, after?: () => void) => {
    setBusy(true);
    try {
      await operation();
      message.success(successText);
      after?.();
      load();
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const openDetail = async (row: QmsD8) => {
    if (!projectId) return;
    try {
      setDetail(await getD8(projectId, row.id));
    } catch (e) {
      message.error(apiErrorText(e));
    }
  };

  const downloadEvidence = async (row: QmsD8) => {
    if (!projectId) return;
    try {
      const result = await exportD8Evidence(projectId, row.id);
      // 经既有 evidence-export 下载端点取回（带 token），axios blob 保存
      const { default: apiClient } = await import("../api/client");
      const response = await apiClient.get(result.download, { responseType: "blob" });
      const url = URL.createObjectURL(response.data as Blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `d8-evidence-${row.code}.zip`;
      link.click();
      URL.revokeObjectURL(url);
      message.success(zh ? "证据包已导出" : "Evidence exported");
    } catch (e) {
      message.error(apiErrorText(e));
    }
  };

  const columns = [
    { title: zh ? "编号" : "Code", dataIndex: "code", key: "code", width: 140 },
    { title: zh ? "标题" : "Title", dataIndex: "title", key: "title" },
    {
      title: zh ? "当前步" : "Step", dataIndex: "current_step", key: "step", width: 90,
      render: (value: number) => `D0–D8 · ${value}/9`,
    },
    {
      title: "D6", dataIndex: "d6_passed", key: "d6", width: 90,
      render: (value: boolean) => (value ? <Tag color="green">{zh ? "通过" : "Pass"}</Tag> : <Tag color="orange">{zh ? "未过" : "Fail"}</Tag>),
    },
    {
      title: zh ? "状态" : "Status", key: "status", width: 90,
      render: (_: unknown, row: QmsD8) => (row.closed_at ? <Tag color="green">{zh ? "已结案" : "Closed"}</Tag> : <Tag>{zh ? "进行中" : "Open"}</Tag>),
    },
    {
      title: zh ? "操作" : "Actions", key: "actions", width: 300,
      render: (_: unknown, row: QmsD8) => (
        <Space wrap>
          <Button size="small" onClick={() => void openDetail(row)}>{zh ? "详情" : "Detail"}</Button>
          {!row.closed_at && (
            <>
              <Button size="small" type="primary" loading={busy}
                onClick={() => void run(() => advanceD8(projectId!, row.id, {}), zh ? "已推进一步" : "Advanced")}>
                {zh ? "推进" : "Advance"}
              </Button>
              {/* D6 验证结论只在第 6 步可登记（后端 D8_D6_STEP_MISMATCH 门禁同步） */}
              {row.current_step === 6 && (
                <Button size="small" loading={busy}
                  onClick={() => void run(() => advanceD8(projectId!, row.id, { d6_passed: true }), zh ? "D6 已登记通过" : "D6 passed")}>
                  {zh ? "D6 通过" : "D6 pass"}
                </Button>
              )}
              <Button size="small" onClick={() => { setDraftTarget(row); draftForm.resetFields(); setDraftOpen(true); }}>
                {zh ? "LLM 起草" : "LLM draft"}
              </Button>
              <Button size="small" type="primary" ghost loading={busy}
                onClick={() => void run(() => closeD8(projectId!, row.id), zh ? "已结案" : "Closed")}>
                {zh ? "结案" : "Close"}
              </Button>
            </>
          )}
          <Button size="small" onClick={() => void downloadEvidence(row)}>{zh ? "证据包" : "Evidence"}</Button>
        </Space>
      ),
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_d8" testId="v2-quality-d8">
        <PageHeading
          section="quality"
          navKey="quality_d8"
          desc={zh
            ? "8D 报告：D0–D8 顺序推进（跳步被拒）；D6（永久对策验证）未通过不得结案；LLM 起草 D1–D5 初稿自动入动作审计；证据包打包 8D 全量 + NCR 轨迹 + 来源预警证据。"
            : "8D reports: sequential D0–D8 steps, D6 gate, LLM drafting and evidence export."}
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
              <Button type="primary" icon={<PlusOutlined />} data-testid="new-d8"
                onClick={() => { form.resetFields(); setCreateOpen(true); }}>
                {zh ? "开立 8D" : "New 8D"}
              </Button>
            </Space>
          }
        />
        <Card>
          <Table
            rowKey="id" size="small" columns={columns} dataSource={rows} pagination={false}
            locale={{ emptyText: zh ? "暂无 8D 报告：点击「开立 8D」创建第一条（可关联 NCR）" : "No 8D reports yet" }}
          />
          <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
            {zh ? "8D 方法口径待质量专家评审（持续登记）。" : "8D methodology pending quality expert review."}
          </Typography.Paragraph>
        </Card>

        <Modal open={createOpen} destroyOnClose title={zh ? "开立 8D 报告" : "New 8D report"}
          okText={zh ? "创建" : "Create"} confirmLoading={busy}
          onCancel={() => setCreateOpen(false)} onOk={() => form.submit()}>
          <Form form={form} layout="vertical" data-testid="d8-form"
            onFinish={(values) => void run(async () => {
              await createD8(projectId!, {
                code: values.code.trim(), title: values.title.trim(),
                ncr_id: values.ncr_id?.trim() || null,
              });
              setCreateOpen(false);
            }, zh ? "8D 已开立" : "8D created")}>
            <Form.Item name="code" label={zh ? "编号" : "Code"} rules={[{ required: true }]}>
              <Input maxLength={64} placeholder="8D-2026-001" />
            </Form.Item>
            <Form.Item name="title" label={zh ? "标题" : "Title"} rules={[{ required: true }]}>
              <Input maxLength={256} />
            </Form.Item>
            <Form.Item name="ncr_id" label={zh ? "关联 NCR ID（可选）" : "Linked NCR ID (optional)"}>
              <Input placeholder="UUID" />
            </Form.Item>
          </Form>
        </Modal>

        <Modal open={draftOpen} destroyOnClose title={zh ? "LLM 起草 D1–D5 初稿" : "LLM draft D1–D5"}
          okText={zh ? "起草" : "Draft"} confirmLoading={busy}
          onCancel={() => setDraftOpen(false)} onOk={() => draftForm.submit()}>
          <Typography.Paragraph type="secondary">
            {zh ? "起草经 LLM 网关完成，自动记入智能体动作审计；网关不可用时回退骨架草稿。" : "Drafting goes through the LLM gateway and is captured in the agent action audit."}
          </Typography.Paragraph>
          <Form form={draftForm} layout="vertical" data-testid="d8-draft-form"
            onFinish={(values) => void run(async () => {
              const result = await draftD8(projectId!, draftTarget!.id, values.context.trim());
              message.info(result.via === "llm" ? (zh ? "LLM 草稿已写入" : "LLM draft saved") : zh ? "网关不可用，已写入骨架草稿" : "Fallback skeleton draft");
              setDraftOpen(false);
            }, zh ? "草稿已生成" : "Drafted")}>
            <Form.Item name="context" label={zh ? "问题背景" : "Context"} rules={[{ required: true }]}>
              <Input.TextArea rows={4} maxLength={2000}
                placeholder={zh ? "现象、对象、发生时机与影响范围…" : "Symptoms, scope and impact..."} />
            </Form.Item>
          </Form>
        </Modal>

        <Modal open={detail !== null} footer={null} onCancel={() => setDetail(null)}
          title={detail ? `${detail.code} · ${detail.title}` : ""} width={720}>
          {detail && (
            <>
              <Descriptions size="small" column={2}>
                <Descriptions.Item label={zh ? "当前步" : "Step"}>{detail.current_step}/9</Descriptions.Item>
                <Descriptions.Item label="D6">{detail.d6_passed ? (zh ? "通过" : "Pass") : zh ? "未过" : "Fail"}</Descriptions.Item>
                <Descriptions.Item label={zh ? "关联 NCR" : "NCR"}>{detail.ncr_id ?? "-"}</Descriptions.Item>
                <Descriptions.Item label={zh ? "结案时间" : "Closed at"}>{detail.closed_at ?? "-"}</Descriptions.Item>
              </Descriptions>
              <Typography.Title level={5} style={{ marginTop: 16 }}>{zh ? "步骤内容" : "Steps"}</Typography.Title>
              {Object.entries(detail.steps).map(([step, content]) => (
                <Typography.Paragraph key={step} style={{ margin: 0 }}>
                  <Tag>D{step}</Tag>
                  {content.drafted ? (zh ? "（LLM 草稿）" : "(LLM draft)") : ""}
                  {content.confirmed_at && <Typography.Text type="secondary"> · {content.confirmed_at}</Typography.Text>}
                  <br />
                  <Typography.Text code>{JSON.stringify(content.content)}</Typography.Text>
                </Typography.Paragraph>
              ))}
            </>
          )}
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
