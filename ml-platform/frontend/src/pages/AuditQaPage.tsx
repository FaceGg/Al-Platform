import { useCallback, useEffect, useState } from "react";
import {
  App as AntApp, Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Typography,
} from "antd";
import { DownloadOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import { apiErrorText } from "../api/qualityAlerts";
import {
  AUDIT_TEMPLATES, askMetrics, auditReportExportUrl, createAuditReport,
  getAuditReport, listAuditReports, listMetricRegistry,
} from "../api/auditQa";
import type { AskMetricsResult, AuditReport, AuditTemplateKey, MetricRegistryItem } from "../api/auditQa";
import { useI18n } from "../i18n";

/** 审计问答（补齐路线第二批 B2-01，导航归属计划 §10.2「智能体中心 ·
 * 知识与对话」新菜单）：问数只走指标注册表（LLM 不生成 SQL）；审计报告
 * 十类模板 = 结构化证据 + 全局唯一引用编号 + 生成后校验，可重开可导出。 */

export default function AuditQaPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projects, projectId, setProjectId } = useQualityAlertLookups();
  const [reports, setReports] = useState<AuditReport[]>([]);
  const [metrics, setMetrics] = useState<MetricRegistryItem[]>([]);
  const [detail, setDetail] = useState<AuditReport | null>(null);
  const [askResult, setAskResult] = useState<AskMetricsResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [reportModalOpen, setReportModalOpen] = useState(false);
  const [askForm] = Form.useForm<{ question: string }>();
  const [reportForm] = Form.useForm<{ template_key: AuditTemplateKey }>();

  const load = useCallback(() => {
    if (!projectId) { setReports([]); setMetrics([]); return; }
    listAuditReports(projectId).then(setReports).catch((e) => message.error(apiErrorText(e)));
    listMetricRegistry(projectId).then((res) => setMetrics(res.items)).catch(() => setMetrics([]));
  }, [projectId, message]);

  useEffect(() => { load(); }, [load]);

  const run = async (operation: () => Promise<unknown>, successText?: string) => {
    setBusy(true);
    try {
      await operation();
      if (successText) message.success(successText);
      load();
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const ask = async (values: { question: string }) => {
    setBusy(true);
    try {
      setAskResult(await askMetrics(projectId!, values.question.trim()));
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const openReport = async (reportId: string) => {
    if (!projectId) return;
    try {
      setDetail(await getAuditReport(projectId, reportId));
    } catch (e) {
      message.error(apiErrorText(e));
    }
  };

  const exportReport = (row: AuditReport) => {
    if (!projectId) return;
    const anchor = document.createElement("a");
    anchor.href = auditReportExportUrl(projectId, row.id);
    anchor.download = `audit-report-${row.template_key}-${row.id.slice(0, 8)}.md`;
    anchor.click();
  };

  const reportColumns = [
    {
      title: zh ? "模板" : "Template", dataIndex: "template_key", key: "template", width: 140,
      render: (value: string) => AUDIT_TEMPLATES.find((item) => item.key === value)?.[zh ? "zh" : "en"] ?? value,
    },
    {
      title: zh ? "状态" : "Status", dataIndex: "status", key: "status", width: 100,
      render: (value: string) => <Tag color={value === "published" ? "green" : "orange"}>{value}</Tag>,
    },
    { title: zh ? "生成时间" : "Created", dataIndex: "created_at", key: "created_at", width: 180 },
    {
      title: zh ? "操作" : "Actions", key: "actions", width: 160,
      render: (_: unknown, row: AuditReport) => (
        <Space>
          <Button size="small" aria-label={`查看报告 ${row.id}`} onClick={() => void openReport(row.id)}>
            {zh ? "查看" : "View"}
          </Button>
          <Button size="small" icon={<DownloadOutlined />} aria-label={`导出报告 ${row.id}`} onClick={() => exportReport(row)}>
            {zh ? "导出" : "Export"}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="agent" navKey="audit_qa" testId="v2-audit-qa">
        <PageHeading
          section="agent"
          navKey="audit_qa"
          desc={zh
            ? "审计问答与问数：问数只走指标注册表（命名绑定参数，LLM 不生成 SQL），返回 answered / clarify / denied 三态；审计报告十类模板由结构化证据生成，带全局唯一引用编号与生成后校验，历史报告可重开。"
            : "Audit QA & ask-metrics: registry-only metric lookup and evidence-based audit reports."}
          actions={
            <Select
              aria-label={zh ? "选择项目" : "Select project"}
              style={{ minWidth: 180 }}
              placeholder={zh ? "选择项目" : "Select project"}
              value={projectId ?? undefined}
              onChange={(value: string) => setProjectId(value)}
              options={projects.map((item) => ({ value: item.id, label: item.name }))}
            />
          }
        />

        {!projectId ? (
          <Card>
            <Typography.Paragraph type="secondary" data-testid="audit-qa-empty">
              {zh ? "选择项目后开始问数或生成审计报告。" : "Select a project to start."}
            </Typography.Paragraph>
          </Card>
        ) : (
          <>
            <Card title={zh ? "问数（指标注册表）" : "Ask metrics"} size="small" style={{ marginBottom: 16 }}>
              <Form form={askForm} layout="inline" data-testid="ask-form"
                onFinish={(values) => void ask(values)}>
                <Form.Item name="question" rules={[{ required: true, max: 500 }]}>
                  <Input style={{ minWidth: 320 }} maxLength={500}
                    placeholder={zh ? "例如：本月质量预警有多少" : "e.g. how many alerts this month"}
                    data-testid="ask-question" />
                </Form.Item>
                <Form.Item>
                  <Button type="primary" htmlType="submit" icon={<QuestionCircleOutlined />}
                    loading={busy} data-testid="ask-submit">{zh ? "提问" : "Ask"}</Button>
                </Form.Item>
              </Form>
              {askResult && (
                <div style={{ marginTop: 12 }} data-testid="ask-result">
                  {askResult.status === "answered" ? (
                    <Typography.Paragraph>
                      <Tag color="green">answered</Tag>
                      <Typography.Text strong>{String(askResult.metric ?? "")}</Typography.Text>
                      {" = "}
                      <Typography.Text code>{String(askResult.value ?? "-")}</Typography.Text>
                      {askResult.footnote && (
                        <Typography.Text type="secondary">（{askResult.footnote}）</Typography.Text>
                      )}
                    </Typography.Paragraph>
                  ) : askResult.status === "clarify" ? (
                    <Typography.Paragraph>
                      <Tag color="orange">clarify</Tag>{askResult.message}
                      {(askResult.candidates ?? []).map((item) => <Tag key={item}>{item}</Tag>)}
                    </Typography.Paragraph>
                  ) : (
                    <Typography.Paragraph>
                      <Tag color="red">denied</Tag>{askResult.message}
                    </Typography.Paragraph>
                  )}
                </div>
              )}
              {metrics.length > 0 && (
                <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
                  {zh ? "注册表指标：" : "Registry metrics: "}
                  {metrics.map((item) => <Tag key={item.name}>{item.name}</Tag>)}
                </Typography.Paragraph>
              )}
            </Card>

            <Card title={zh ? "审计报告" : "Audit reports"} size="small"
              extra={
                <Button type="primary" size="small" data-testid="new-report"
                  onClick={() => { reportForm.resetFields(); setReportModalOpen(true); }}>
                  {zh ? "生成报告" : "New report"}
                </Button>
              }>
              <Table rowKey="id" size="small" columns={reportColumns} dataSource={reports} pagination={false}
                locale={{ emptyText: zh ? "暂无报告：选择模板生成第一份（结构化证据 + 引用编号）" : "No reports yet" }} />
            </Card>
          </>
        )}

        <Modal open={reportModalOpen} destroyOnClose title={zh ? "生成审计报告" : "New audit report"}
          okText={zh ? "生成" : "Create"} confirmLoading={busy}
          onCancel={() => setReportModalOpen(false)} onOk={() => reportForm.submit()}>
          <Typography.Paragraph type="secondary">
            {zh ? "报告由结构化证据生成（LLM 不自由发挥），生成后校验引用；LLM 叙述不可用时回退结构化要点并如实标注。" : "Reports are generated from structured evidence."}
          </Typography.Paragraph>
          <Form form={reportForm} layout="vertical" data-testid="report-form"
            onFinish={(values) => void run(async () => {
              const report = await createAuditReport(projectId!, values.template_key);
              setDetail(report);
              setReportModalOpen(false);
            }, zh ? "报告已生成" : "Report created")}>
            <Form.Item name="template_key" label={zh ? "模板" : "Template"} rules={[{ required: true }]}>
              <Select options={AUDIT_TEMPLATES.map((item) => ({ value: item.key, label: zh ? item.zh : item.en }))}
                data-testid="report-template" />
            </Form.Item>
          </Form>
        </Modal>

        <Modal open={detail !== null} footer={null} width={760}
          onCancel={() => setDetail(null)} title={detail?.template_key}>
          {detail && (
            <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>
              {detail.content_markdown}
            </Typography.Paragraph>
          )}
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
