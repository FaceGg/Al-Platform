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
import { createCase, getCase, listCases, repushCase } from "../api/qms";
import type { QmsCase, QmsCaseDetail } from "../api/qms";
import { useI18n } from "../i18n";

/** 质量管理 · 质量体系 / 案例中心（B3-07）：critical 预警关闭自动开案 + 手工开案；
 * 时间线=关联对象（处置/NCR/8D/知识/报告/控制计划版本）；NCR 关闭→状态重推。 */

const SEVERITY_COLOR: Record<string, string> = {
  low: "default", medium: "blue", high: "orange", critical: "red",
};

export default function QualityCasesPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projects, projectId, setProjectId } = useQualityAlertLookups();
  const [rows, setRows] = useState<QmsCase[]>([]);
  const [keyword, setKeyword] = useState("");
  const [detail, setDetail] = useState<QmsCaseDetail | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkTarget, setLinkTarget] = useState<QmsCase | null>(null);
  const [linkForm] = Form.useForm<{ object_type: string; object_id: string }>();
  const [form] = Form.useForm<{ code: string; title: string; severity: string; source_alert_id?: string; keywords?: string }>();
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!projectId) { setRows([]); return; }
    listCases(projectId, keyword.trim() ? { keyword: keyword.trim() } : undefined)
      .then(setRows).catch((e) => message.error(apiErrorText(e)));
  }, [projectId, keyword, message]);

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

  const openDetail = async (row: QmsCase) => {
    if (!projectId) return;
    try {
      setDetail(await getCase(projectId, row.id));
    } catch (e) {
      message.error(apiErrorText(e));
    }
  };

  const columns = [
    { title: zh ? "编号" : "Code", dataIndex: "code", key: "code", width: 140 },
    { title: zh ? "标题" : "Title", dataIndex: "title", key: "title" },
    {
      title: zh ? "严重度" : "Severity", dataIndex: "severity", key: "severity", width: 100,
      render: (value: string) => <Tag color={SEVERITY_COLOR[value]}>{value}</Tag>,
    },
    {
      title: zh ? "状态" : "Status", dataIndex: "status", key: "status", width: 110,
      render: (value: string) => (
        <Tag color={value === "closed" ? "green" : value === "monitoring" ? "purple" : "blue"}>{value}</Tag>
      ),
    },
    {
      title: zh ? "操作" : "Actions", key: "actions", width: 240,
      render: (_: unknown, row: QmsCase) => (
        <Space>
          <Button size="small" onClick={() => void openDetail(row)}>{zh ? "详情" : "Detail"}</Button>
          {row.status !== "closed" && (
            <>
              <Button size="small" onClick={() => { setLinkTarget(row); linkForm.resetFields(); setLinkOpen(true); }}>
                {zh ? "关联对象" : "Link"}
              </Button>
              <Button size="small" type="primary" ghost loading={busy}
                onClick={() => void run(() => repushCase(projectId!, row.id), zh ? "状态已重推" : "Repushed")}>
                {zh ? "状态重推" : "Repush"}
              </Button>
            </>
          )}
        </Space>
      ),
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_cases" testId="v2-quality-cases">
        <PageHeading
          section="quality"
          navKey="quality_cases"
          desc={zh
            ? "案例中心：critical 预警关闭时自动开案（可手工开案）；关联对象构成案例时间线；关联 NCR 全部关闭且无未决 8D 时状态重推为 closed。"
            : "Case center: auto-opened from closed critical alerts, linked-object timeline and status repush."}
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
              <Input.Search
                allowClear placeholder={zh ? "关键词检索" : "Keyword"} style={{ width: 200 }}
                onSearch={(value) => setKeyword(value)}
              />
              <Button type="primary" icon={<PlusOutlined />} data-testid="new-case"
                onClick={() => { form.resetFields(); setCreateOpen(true); }}>
                {zh ? "开案" : "New case"}
              </Button>
            </Space>
          }
        />
        <Card>
          <Table
            rowKey="id" size="small" columns={columns} dataSource={rows} pagination={false}
            locale={{ emptyText: zh ? "暂无案例：critical 预警关闭时自动开案，也可手工开案" : "No cases yet" }}
          />
        </Card>

        <Modal open={createOpen} destroyOnClose title={zh ? "手工开案" : "New case"}
          okText={zh ? "创建" : "Create"} confirmLoading={busy}
          onCancel={() => setCreateOpen(false)} onOk={() => form.submit()}>
          <Form form={form} layout="vertical" data-testid="case-form" initialValues={{ severity: "medium" }}
            onFinish={(values) => void run(async () => {
              await createCase(projectId!, {
                code: values.code.trim(), title: values.title.trim(),
                severity: values.severity,
                source_alert_id: values.source_alert_id?.trim() || null,
                keywords: values.keywords?.trim() || null,
              });
              setCreateOpen(false);
            }, zh ? "案例已创建" : "Case created")}>
            <Form.Item name="code" label={zh ? "编号" : "Code"} rules={[{ required: true }]}>
              <Input maxLength={64} placeholder="CASE-2026-001" />
            </Form.Item>
            <Form.Item name="title" label={zh ? "标题" : "Title"} rules={[{ required: true }]}>
              <Input maxLength={256} />
            </Form.Item>
            <Form.Item name="severity" label={zh ? "严重度" : "Severity"}>
              <Select options={[
                { value: "low", label: "low" }, { value: "medium", label: "medium" },
                { value: "high", label: "high" }, { value: "critical", label: "critical" },
              ]} />
            </Form.Item>
            <Form.Item name="source_alert_id" label={zh ? "来源预警 ID（可选）" : "Source alert ID (optional)"}>
              <Input placeholder="UUID" />
            </Form.Item>
            <Form.Item name="keywords" label={zh ? "关键词" : "Keywords"}>
              <Input maxLength={256} />
            </Form.Item>
          </Form>
        </Modal>

        <Modal open={linkOpen} destroyOnClose title={zh ? "关联对象" : "Link object"}
          okText={zh ? "关联" : "Link"} confirmLoading={busy}
          onCancel={() => setLinkOpen(false)} onOk={() => linkForm.submit()}>
          <Form form={linkForm} layout="vertical" data-testid="case-link-form"
            onFinish={(values) => void run(async () => {
              const { linkCaseObject } = await import("../api/qms");
              await linkCaseObject(projectId!, linkTarget!.id, values.object_type, values.object_id.trim());
              setLinkOpen(false);
            }, zh ? "已关联" : "Linked")}>
            <Form.Item name="object_type" label={zh ? "对象类型" : "Object type"} rules={[{ required: true }]}>
              <Select options={[
                { value: "ncr_capa", label: "NCR" }, { value: "d8_report", label: "8D" },
                { value: "quality_alert", label: zh ? "预警" : "Alert" },
                { value: "knowledge", label: zh ? "知识条目" : "Knowledge" },
                { value: "quality_report", label: zh ? "质量报告" : "Report" },
                { value: "control_plan", label: zh ? "控制计划版本" : "Control plan" },
              ]} />
            </Form.Item>
            <Form.Item name="object_id" label="Object ID" rules={[{ required: true }]}>
              <Input placeholder="UUID / 编号" />
            </Form.Item>
          </Form>
        </Modal>

        <Modal open={detail !== null} footer={null} onCancel={() => setDetail(null)}
          title={detail ? `${detail.code} · ${detail.title}` : ""} width={640}>
          {detail && (
            <>
              <Descriptions size="small" column={2}>
                <Descriptions.Item label={zh ? "严重度" : "Severity"}><Tag color={SEVERITY_COLOR[detail.severity]}>{detail.severity}</Tag></Descriptions.Item>
                <Descriptions.Item label={zh ? "状态" : "Status"}>{detail.status}</Descriptions.Item>
                <Descriptions.Item label={zh ? "来源预警" : "Source alert"}>{detail.source_alert_id ?? "-"}</Descriptions.Item>
                <Descriptions.Item label={zh ? "关键词" : "Keywords"}>{detail.keywords ?? "-"}</Descriptions.Item>
              </Descriptions>
              <Typography.Title level={5} style={{ marginTop: 16 }}>{zh ? "关联对象（时间线）" : "Linked objects (timeline)"}</Typography.Title>
              {detail.links.length === 0 && <Typography.Text type="secondary">{zh ? "暂无关联对象" : "No linked objects"}</Typography.Text>}
              {detail.links.map((item, index) => (
                <Typography.Paragraph key={index} style={{ margin: 0 }}>
                  <Tag>{item.object_type}</Tag>{item.object_id}
                </Typography.Paragraph>
              ))}
            </>
          )}
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
