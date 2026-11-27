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
import { createNcr, getNcr, listNcr, rejectNcr, transitionNcr } from "../api/qms";
import type { QmsNcr, QmsNcrDetail } from "../api/qms";
import { useI18n } from "../i18n";

/** 质量管理 · 质量体系 / NCR-CAPA（B3-04）：五阶段顺序推进 + 早期驳回 +
 * 关闭门禁=连续三个验证周期无复发（IATF 16949 口径待质量专家评审）。 */

const STAGE_COLOR: Record<string, string> = {
  draft: "default", analysis: "blue", action: "orange",
  verification: "purple", closed: "green", rejected: "red",
};

export default function QualityNcrPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projects, projectId, setProjectId } = useQualityAlertLookups();
  const [rows, setRows] = useState<QmsNcr[]>([]);
  const [detail, setDetail] = useState<QmsNcrDetail | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectTarget, setRejectTarget] = useState<QmsNcr | null>(null);
  const [form] = Form.useForm<{ code: string; title: string; source_alert_id?: string }>();
  const [rejectForm] = Form.useForm<{ reason: string }>();
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!projectId) { setRows([]); return; }
    listNcr(projectId).then(setRows).catch((e) => message.error(apiErrorText(e)));
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

  const openDetail = async (row: QmsNcr) => {
    if (!projectId) return;
    try {
      setDetail(await getNcr(projectId, row.id));
    } catch (e) {
      message.error(apiErrorText(e));
    }
  };

  const columns = [
    { title: zh ? "编号" : "Code", dataIndex: "code", key: "code", width: 140 },
    { title: zh ? "标题" : "Title", dataIndex: "title", key: "title" },
    {
      title: zh ? "阶段" : "Stage", dataIndex: "stage", key: "stage", width: 110,
      render: (value: string) => <Tag color={STAGE_COLOR[value]}>{value}</Tag>,
    },
    {
      title: zh ? "验证周期" : "Cycles", dataIndex: "verification_cycles", key: "cycles", width: 90,
      render: (value: number) => `${value}/3`,
    },
    {
      title: zh ? "操作" : "Actions", key: "actions", width: 220,
      render: (_: unknown, row: QmsNcr) => (
        <Space>
          <Button size="small" onClick={() => void openDetail(row)}>{zh ? "详情" : "Detail"}</Button>
          {row.stage !== "closed" && row.stage !== "rejected" && (
            <Button size="small" type="primary" loading={busy} data-testid={`advance-${row.code}`}
              onClick={() => void run(() => transitionNcr(projectId!, row.id), zh ? "已推进" : "Advanced")}>
              {row.stage === "verification" ? (zh ? "尝试关闭" : "Try close") : (zh ? "推进" : "Advance")}
            </Button>
          )}
          {(row.stage === "draft" || row.stage === "analysis") && (
            <Button size="small" danger onClick={() => { setRejectTarget(row); rejectForm.resetFields(); setRejectOpen(true); }}>
              {zh ? "驳回" : "Reject"}
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_ncr" testId="v2-quality-ncr">
        <PageHeading
          section="quality"
          navKey="quality_ncr"
          desc={zh
            ? "不合格与纠正措施：draft → analysis → action → verification → closed 五阶段顺序推进，跳步被拒；draft/analysis 可驳回（理由必填）；关闭门禁 = 连续三个验证周期（每周期 7 天）同场景同工位无复发。"
            : "NCR/CAPA: five sequential stages with early rejection and a three-cycle no-recurrence close gate."}
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
              <Button type="primary" icon={<PlusOutlined />} data-testid="new-ncr"
                onClick={() => { form.resetFields(); setCreateOpen(true); }}>
                {zh ? "登记 NCR" : "New NCR"}
              </Button>
            </Space>
          }
        />
        <Card>
          <Table
            rowKey="id" size="small" columns={columns} dataSource={rows} pagination={false}
            locale={{ emptyText: zh ? "暂无 NCR：点击「登记 NCR」创建第一条，或从预警转入" : "No NCRs yet" }}
          />
          <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
            {zh
              ? "关闭门禁口径：验证期内同场景+同工位出现新预警即判复发、周期清零；三周期达标方可关闭（NCR_CLOSE_BLOCKED）。IATF 16949 口径待质量专家评审。"
              : "Recurrence resets the cycle counter; three clean cycles are required to close."}
          </Typography.Paragraph>
        </Card>

        <Modal open={createOpen} destroyOnClose title={zh ? "登记 NCR" : "New NCR"}
          okText={zh ? "创建" : "Create"} confirmLoading={busy}
          onCancel={() => setCreateOpen(false)} onOk={() => form.submit()}>
          <Form form={form} layout="vertical" data-testid="ncr-form"
            onFinish={(values) => void run(async () => {
              await createNcr(projectId!, {
                code: values.code.trim(), title: values.title.trim(),
                source_alert_id: values.source_alert_id?.trim() || null,
              });
              setCreateOpen(false);
            }, zh ? "NCR 已登记" : "NCR created")}>
            <Form.Item name="code" label={zh ? "编号" : "Code"} rules={[{ required: true }]}>
              <Input maxLength={64} placeholder="NCR-2026-001" />
            </Form.Item>
            <Form.Item name="title" label={zh ? "标题" : "Title"} rules={[{ required: true }]}>
              <Input maxLength={256} />
            </Form.Item>
            <Form.Item name="source_alert_id" label={zh ? "来源预警 ID（可选，从预警转入带证据链）" : "Source alert ID (optional)"}>
              <Input placeholder="UUID" />
            </Form.Item>
          </Form>
        </Modal>

        <Modal open={rejectOpen} destroyOnClose title={zh ? "驳回 NCR" : "Reject NCR"}
          okText={zh ? "驳回" : "Reject"} confirmLoading={busy}
          onCancel={() => setRejectOpen(false)} onOk={() => rejectForm.submit()}>
          <Typography.Paragraph type="secondary">
            {zh ? "仅 draft / analysis 阶段可驳回；理由必填，驳回为终态。" : "Only draft/analysis stages can be rejected; reason required."}
          </Typography.Paragraph>
          <Form form={rejectForm} layout="vertical" data-testid="ncr-reject-form"
            onFinish={(values) => void run(async () => {
              await rejectNcr(projectId!, rejectTarget!.id, values.reason.trim());
              setRejectOpen(false);
            }, zh ? "已驳回" : "Rejected")}>
            <Form.Item name="reason" label={zh ? "驳回理由" : "Reason"} rules={[{ required: true }]}>
              <Input.TextArea rows={3} maxLength={500} />
            </Form.Item>
          </Form>
        </Modal>

        <Modal open={detail !== null} footer={null} onCancel={() => setDetail(null)}
          title={detail ? `${detail.code} · ${detail.title}` : ""} width={640}>
          {detail && (
            <>
              <Descriptions size="small" column={2}>
                <Descriptions.Item label={zh ? "阶段" : "Stage"}><Tag color={STAGE_COLOR[detail.stage]}>{detail.stage}</Tag></Descriptions.Item>
                <Descriptions.Item label={zh ? "验证周期" : "Cycles"}>{detail.verification_cycles}/3</Descriptions.Item>
                <Descriptions.Item label={zh ? "来源预警" : "Source alert"}>{detail.source_alert_id ?? "-"}</Descriptions.Item>
                <Descriptions.Item label={zh ? "关闭时间" : "Closed at"}>{detail.closed_at ?? "-"}</Descriptions.Item>
                {detail.reject_reason && (
                  <Descriptions.Item label={zh ? "驳回理由" : "Reject reason"} span={2}>{detail.reject_reason}</Descriptions.Item>
                )}
              </Descriptions>
              <Typography.Title level={5} style={{ marginTop: 16 }}>{zh ? "轨迹" : "Trail"}</Typography.Title>
              {detail.actions.map((item, index) => (
                <Typography.Paragraph key={index} style={{ margin: 0 }}>
                  <Tag>{item.phase}</Tag>{item.action}
                  {item.created_at && <Typography.Text type="secondary"> · {item.created_at}</Typography.Text>}
                </Typography.Paragraph>
              ))}
            </>
          )}
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
