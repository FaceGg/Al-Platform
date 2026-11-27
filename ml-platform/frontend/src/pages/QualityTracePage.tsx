import { useState } from "react";
import { App as AntApp, Button, Card, Descriptions, Input, Select, Space, Table, Tag, Typography } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import { apiErrorText } from "../api/qualityAlerts";
import { traceBatch, traceSample } from "../api/qms";
import type { QmsTraceBatch, QmsTraceResult } from "../api/qms";
import { useI18n } from "../i18n";

/** 质量管理 · 质量体系 / 批次追溯（B3-09）：单样本四对象串联（原始数据 → 模型判定
 * → 预警 → NCR）+ 按批次键的批次概览；无批次键的数据集在接入时已被 B1-10 把关。 */

export default function QualityTracePage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projects, projectId, setProjectId } = useQualityAlertLookups();
  const [sampleKey, setSampleKey] = useState("");
  const [batchNo, setBatchNo] = useState("");
  const [sampleResult, setSampleResult] = useState<QmsTraceResult | null>(null);
  const [batchResult, setBatchResult] = useState<QmsTraceBatch | null>(null);
  const [busy, setBusy] = useState(false);

  const runSample = async () => {
    if (!projectId || !sampleKey.trim()) return;
    setBusy(true);
    try {
      setSampleResult(await traceSample(projectId, sampleKey.trim()));
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const runBatch = async () => {
    if (!projectId || !batchNo.trim()) return;
    setBusy(true);
    try {
      setBatchResult(await traceBatch(projectId, batchNo.trim()));
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_trace" testId="v2-quality-trace">
        <PageHeading
          section="quality"
          navKey="quality_trace"
          desc={zh
            ? "批次追溯：样本键串起 原始数据（数据集版本）→ 模型判定（推理明细）→ 预警 → NCR 四对象；批次概览按批次键聚合样本数、推理明细与预警。"
            : "Traceability: sample-level four-object chain and batch-level overview."}
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
        <Card title={zh ? "样本追溯" : "Sample trace"}>
          <Space style={{ marginBottom: 12 }} wrap>
            <Input allowClear style={{ width: 360 }} placeholder={zh ? "业务样本键（如 VIN）" : "Sample key"}
              value={sampleKey} onChange={(e) => setSampleKey(e.target.value)}
              onPressEnter={() => void runSample()} />
            <Button type="primary" icon={<SearchOutlined />} loading={busy} data-testid="trace-sample"
              onClick={() => void runSample()}>
              {zh ? "追溯" : "Trace"}
            </Button>
          </Space>
          {sampleResult === null ? (
            <Typography.Text type="secondary">
              {zh ? "输入样本键后追溯四对象链条；无结果显示空链。" : "Enter a sample key to trace."}
            </Typography.Text>
          ) : (
            <Descriptions size="small" column={2} bordered data-testid="trace-result">
              <Descriptions.Item label={zh ? "样本键" : "Sample key"}>{sampleResult.sample_key}</Descriptions.Item>
              <Descriptions.Item label={zh ? "数据集版本" : "Dataset versions"}>
                {sampleResult.trace_links.map((item, index) => (
                  <div key={index}>{item.dataset_version_id ?? "-"}{item.batch_no ? `（${item.batch_no}）` : ""}</div>
                ))}
                {sampleResult.trace_links.length === 0 && "-"}
              </Descriptions.Item>
              <Descriptions.Item label={zh ? "模型判定" : "Inference results"}>
                {sampleResult.inference_results.length === 0 ? "-" : sampleResult.inference_results.map((item) => (
                  <div key={item.id}>
                    <Tag>{item.channel}</Tag>{String(item.predicted_label ?? "-")}
                  </div>
                ))}
              </Descriptions.Item>
              <Descriptions.Item label={zh ? "预警" : "Alerts"}>
                {sampleResult.alerts.length === 0 ? "-" : sampleResult.alerts.map((item) => (
                  <div key={item.id}><Tag color={item.severity === "critical" ? "red" : "orange"}>{item.severity}</Tag>{item.title}</div>
                ))}
              </Descriptions.Item>
              <Descriptions.Item label={zh ? "关联 NCR" : "NCRs"} span={2}>
                {sampleResult.ncr_ids.length === 0 ? "-" : sampleResult.ncr_ids.join("、")}
              </Descriptions.Item>
            </Descriptions>
          )}
        </Card>
        <Card title={zh ? "批次概览" : "Batch overview"} style={{ marginTop: 16 }}>
          <Space style={{ marginBottom: 12 }} wrap>
            <Input allowClear style={{ width: 360 }} placeholder={zh ? "批次号" : "Batch no"}
              value={batchNo} onChange={(e) => setBatchNo(e.target.value)}
              onPressEnter={() => void runBatch()} />
            <Button type="primary" icon={<SearchOutlined />} loading={busy} data-testid="trace-batch"
              onClick={() => void runBatch()}>
              {zh ? "查询" : "Query"}
            </Button>
          </Space>
          {batchResult === null ? (
            <Typography.Text type="secondary">
              {zh ? "按批次键聚合：样本键、推理明细、预警与 NCR。" : "Aggregate by batch key."}
            </Typography.Text>
          ) : (
            <>
              <Typography.Paragraph>
                {zh ? "样本数" : "Samples"}: <Typography.Text strong>{batchResult.sample_count}</Typography.Text>
                　{zh ? "预警" : "Alerts"}: <Typography.Text strong>{batchResult.alerts.length}</Typography.Text>
                　NCR: <Typography.Text strong>{batchResult.ncr_ids.length}</Typography.Text>
              </Typography.Paragraph>
              <Table
                rowKey="id" size="small" pagination={false}
                dataSource={batchResult.inference_results.map((item) => ({ ...item, key: item.id }))}
                columns={[
                  { title: zh ? "样本键" : "Sample", dataIndex: "sample_key", key: "sample_key" },
                  { title: zh ? "判定" : "Prediction", dataIndex: "predicted_label", key: "label", render: (v: unknown) => String(v ?? "-") },
                  { title: zh ? "通道" : "Channel", dataIndex: "channel", key: "channel", width: 100 },
                ]}
                locale={{ emptyText: zh ? "该批次无推理明细" : "No inference results" }}
              />
            </>
          )}
        </Card>
      </V2PageFrame>
    </AppLayout>
  );
}
