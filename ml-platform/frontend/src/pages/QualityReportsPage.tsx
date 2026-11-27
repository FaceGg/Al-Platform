import { useCallback, useEffect, useState } from "react";
import {
  App as AntApp, Button, Card, Descriptions, Form, Input, Modal, Select, Space, Table, Tag, Typography,
} from "antd";
import { DownloadOutlined, PlusOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import { apiErrorText } from "../api/qualityAlerts";
import { createReport, listReports } from "../api/qms";
import type { QmsReport } from "../api/qms";
import { useI18n } from "../i18n";

/** 质量管理 · 质量体系 / 质量报告（B3-08）：日报/周报/月报定时生成（beat
 * qms-report-scheduler 600s 巡检上一已完结周期）+ 手工补报；NG 率从
 * quality_aggregates 同源取数（与趋势页同数字）；HTML/JSON 导出。 */

function currentPeriodKey(period: string): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  if (period === "daily") {
    const day = new Date(now.getTime() - 86400000);
    return `${day.getFullYear()}${pad(day.getMonth() + 1)}${pad(day.getDate())}`;
  }
  if (period === "weekly") {
    const lastMonday = new Date(now.getTime() - ((now.getDay() + 6) % 7 + 7) * 86400000);
    const january = new Date(lastMonday.getFullYear(), 0, 1);
    const week = Math.ceil(((lastMonday.getTime() - january.getTime()) / 86400000 + january.getDay() + 1) / 7);
    return `${lastMonday.getFullYear()}W${pad(week)}`;
  }
  const lastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${lastMonth.getFullYear()}${pad(lastMonth.getMonth() + 1)}`;
}

export default function QualityReportsPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projects, projectId, setProjectId } = useQualityAlertLookups();
  const [rows, setRows] = useState<QmsReport[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [detail, setDetail] = useState<QmsReport | null>(null);
  const [form] = Form.useForm<{ period: string; period_key: string }>();
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!projectId) { setRows([]); return; }
    listReports(projectId).then(setRows).catch((e) => message.error(apiErrorText(e)));
  }, [projectId, message]);

  useEffect(() => { load(); }, [load]);

  const download = async (row: QmsReport, format: "html" | "json") => {
    if (!projectId) return;
    try {
      const { default: apiClient } = await import("../api/client");
      const response = await apiClient.get(
        `/projects/${projectId}/qms/quality-reports/${row.id}/export.${format}`,
        { responseType: "blob" },
      );
      const url = URL.createObjectURL(response.data as Blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `quality-report-${row.period}-${row.period_key}.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      message.error(apiErrorText(e));
    }
  };

  const columns = [
    {
      title: zh ? "周期" : "Period", dataIndex: "period", key: "period", width: 90,
      render: (value: string) => <Tag>{value}</Tag>,
    },
    { title: zh ? "周期键" : "Key", dataIndex: "period_key", key: "key", width: 120 },
    {
      title: zh ? "生成方式" : "By", dataIndex: "generated_by", key: "by", width: 110,
      render: (value: string) => <Tag color={value === "scheduler" ? "green" : "blue"}>{value}</Tag>,
    },
    {
      title: "NG 率", key: "ng", width: 100,
      render: (_: unknown, row: QmsReport) => (row.content.ng_rate === null || row.content.ng_rate === undefined
        ? "-" : `${(row.content.ng_rate * 100).toFixed(2)}%`),
    },
    { title: zh ? "预警总量" : "Alerts", key: "alerts", width: 100, render: (_: unknown, row: QmsReport) => row.content.alert_total ?? 0 },
    { title: zh ? "未决 NCR" : "Open NCR", key: "ncr", width: 100, render: (_: unknown, row: QmsReport) => row.content.ncr_open ?? 0 },
    {
      title: zh ? "操作" : "Actions", key: "actions", width: 240,
      render: (_: unknown, row: QmsReport) => (
        <Space>
          <Button size="small" onClick={() => setDetail(row)}>{zh ? "详情" : "Detail"}</Button>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => void download(row, "html")}>HTML</Button>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => void download(row, "json")}>JSON</Button>
        </Space>
      ),
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_reports" testId="v2-quality-reports">
        <PageHeading
          section="quality"
          navKey="quality_reports"
          desc={zh
            ? "质量报告：日报/周报/月报由定时任务对上一已完结周期自动生成（幂等），也可手工补报；NG 率与预警口径从聚合模块同源取数（与趋势页同数字）；Cpk 达标率随 SPC 基线评估接入。"
            : "Quality reports: scheduled daily/weekly/monthly with same-source numbers."}
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
              <Button type="primary" icon={<PlusOutlined />} data-testid="new-report"
                onClick={() => {
                  form.resetFields();
                  form.setFieldsValue({ period: "daily", period_key: currentPeriodKey("daily") });
                  setCreateOpen(true);
                }}>
                {zh ? "手工补报" : "Generate now"}
              </Button>
            </Space>
          }
        />
        <Card>
          <Table
            rowKey="id" size="small" columns={columns} dataSource={rows} pagination={false}
            locale={{ emptyText: zh ? "暂无报告：定时任务每日自动补齐上一周期，也可手工补报" : "No reports yet" }}
          />
          <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
            {zh
              ? "同源口径：NG 率 = 已确认异常 ÷ 已关闭预警（排除演示预警），与趋势页同一取数路径；窗口 [起,止) UTC 见报告详情。"
              : "NG rate shares the same aggregation source as the trends page."}
          </Typography.Paragraph>
        </Card>

        <Modal open={createOpen} destroyOnClose title={zh ? "手工补报" : "Generate report"}
          okText={zh ? "生成" : "Generate"} confirmLoading={busy}
          onCancel={() => setCreateOpen(false)} onOk={() => form.submit()}>
          <Form form={form} layout="vertical" data-testid="report-form"
            onFinish={(values) => {
              setBusy(true);
              createReport(projectId!, values.period, values.period_key.trim())
                .then(() => {
                  message.success(zh ? "报告已生成" : "Report generated");
                  setCreateOpen(false);
                  load();
                })
                .catch((e) => message.error(apiErrorText(e)))
                .finally(() => setBusy(false));
            }}>
            <Form.Item name="period" label={zh ? "周期" : "Period"}>
              <Select options={[
                { value: "daily", label: zh ? "日报" : "Daily" },
                { value: "weekly", label: zh ? "周报" : "Weekly" },
                { value: "monthly", label: zh ? "月报" : "Monthly" },
              ]} />
            </Form.Item>
            <Form.Item name="period_key" label={zh ? "周期键（daily=YYYYMMDD / weekly=YYYYWww / monthly=YYYYMM）" : "Period key"}
              rules={[{ required: true }]}>
              <Input maxLength={16} />
            </Form.Item>
          </Form>
        </Modal>

        <Modal open={detail !== null} footer={null} onCancel={() => setDetail(null)}
          title={detail ? `${detail.period} / ${detail.period_key}` : ""} width={640}>
          {detail && (
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label={zh ? "窗口" : "Window"}>{detail.content.window?.join(" ~ ") ?? "-"}</Descriptions.Item>
              <Descriptions.Item label="NG 率">{detail.content.ng_rate ?? "-"}</Descriptions.Item>
              <Descriptions.Item label="Cpk 达标率">{detail.content.cpk_pass_rate ?? (zh ? "（随 SPC 基线评估接入）" : "pending")}</Descriptions.Item>
              <Descriptions.Item label={zh ? "口径" : "Footnote"}>{detail.content.footnote ?? "-"}</Descriptions.Item>
            </Descriptions>
          )}
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
