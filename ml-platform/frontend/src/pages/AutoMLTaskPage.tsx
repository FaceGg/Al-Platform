import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Col, Descriptions, Divider, Empty, Modal, Progress, Row, Spin, Space, Statistic, Table, Tag, Typography, message } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useNavigate, useParams } from "react-router-dom";
import apiClient, { formatApiError } from "../api/client";
import AppLayout from "../components/AppLayout";

const { Title, Text } = Typography;

function metric(row: Record<string, unknown>, names: string[]): number | null {
  for (const name of names) {
    const value = Number(row[name]);
    if (Number.isFinite(value)) return value;
  }
  for (const nestedName of ["metrics", "evaluation", "scores", "metric"]) {
    const nested = row[nestedName];
    if (nested && typeof nested === "object") {
      const value = metric(nested as Record<string, unknown>, names);
      if (value != null) return value;
    }
  }
  return null;
}

function resultSource(metrics: Record<string, unknown>): Array<Record<string, unknown>> {
  const details = Array.isArray(metrics.algorithm_results)
    ? metrics.algorithm_results.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
    : [];
  const base = Array.isArray(metrics.models) ? metrics.models : Array.isArray(metrics.all_results) ? metrics.all_results : details;
  if (Array.isArray(base)) {
    return base.map((item) => {
      const row = item && typeof item === "object" ? item as Record<string, unknown> : {};
      const detail = details.find((candidate) => String(candidate.algorithm_id || candidate.name) === String(row.algorithm_id || row.name || row.model));
      return detail ? { ...detail, ...row, trials: detail.trials || row.trials } : row;
    });
  }
  return [];
}

export default function AutoMLTaskPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [analysisReport, setAnalysisReport] = useState<Record<string, unknown> | null>(null);
  const [reportGenerating, setReportGenerating] = useState(false);
  const [selectedModel, setSelectedModel] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!taskId) return;
    let active = true;
    const load = async () => {
      try {
        const response = await apiClient.get(`/training/jobs/${taskId}`);
        if (active) { setJob(response.data || {}); setError(undefined); }
      } catch (cause) {
        if (active) setError(formatApiError(cause, "建模任务加载失败"));
      } finally { if (active) setLoading(false); }
    };
    void load();
    const timer = window.setInterval(() => {
      if (!job || !["completed", "failed", "cancelled"].includes(String(job.status))) void load();
    }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [taskId, job?.status]);

  const metrics = (job?.metrics && typeof job.metrics === "object" ? job.metrics : {}) as Record<string, unknown>;
  const progress = (metrics.progress && typeof metrics.progress === "object" ? metrics.progress : {}) as Record<string, unknown>;
  const completed = Number(progress.completed ?? progress.completed_count ?? 0);
  const total = Number(progress.total ?? progress.total_count ?? 0);
  const percent = Number.isFinite(Number(progress.percent)) ? Number(progress.percent) : total > 0 ? Math.round((completed / total) * 100) : 0;
  const rows = useMemo<Array<Record<string, unknown> & { key: string; auc: number | null; f1: number | null }>>(() => {
    const source = resultSource(metrics);
    return source.map((row, index) => {
      return { ...row, key: String(row.id || row.name || row.model || index), auc: metric(row, ["auc", "AUC", "roc_auc", "rocAuc", "roc_auc_score"]), f1: metric(row, ["f1", "F1", "f1_score", "f1_weighted"]) };
    }).sort((left, right) => (right.auc ?? -1) - (left.auc ?? -1) || (right.f1 ?? -1) - (left.f1 ?? -1));
  }, [metrics]);

  const reportReady = String(job?.status) === "completed" && percent >= 100 && rows.length > 0;
  const formatMetric = (value: number | null) => value == null ? "-" : value.toFixed(4);
  const selectedTrials = selectedModel && Array.isArray(selectedModel.trials)
    ? selectedModel.trials as Record<string, unknown>[]
    : [];

  const generateReport = () => {
    if (!job || !reportReady) return;
    setReportGenerating(true);
    setAnalysisReport({
      title: "通用自动建模分析报告",
      generated_at: new Date().toISOString(),
      task_id: taskId,
      task_name: job.name || taskId,
      project_id: job.project_id || null,
      status: job.status || "unknown",
      progress,
      best_model: metrics.best_model || metrics.best_candidate || null,
      models: rows.map(({ key: _key, ...row }) => row),
      metrics,
    });
    setReportGenerating(false);
    message.success("分析报告已生成");
  };

  const exportReport = () => {
    if (!analysisReport) return;
    const blob = new Blob([JSON.stringify(analysisReport, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `automl-analysis-report-${taskId || "task"}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    message.success("分析报告已导出");
  };

  return <AppLayout>
    <div style={{ maxWidth: 1440, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <div><Text type="secondary">通用自动建模</Text><Title level={3} style={{ margin: 0 }}>建模任务进度</Title></div>
        <button type="button" className="ant-btn" onClick={() => navigate("/automl")}>返回任务列表</button>
      </div>
      {error && <Alert type="error" showIcon message={error} />}
      {loading && !job ? <Card><Spin /></Card> : job ? <>
        <Card style={{ marginBottom: 16 }}>
          <Descriptions column={{ xs: 1, sm: 2, md: 4 }} size="small">
            <Descriptions.Item label="任务">{String(job.name || taskId)}</Descriptions.Item>
            <Descriptions.Item label="状态"><Tag color={job.status === "completed" ? "green" : job.status === "failed" ? "red" : "blue"}>{String(job.status || "queued")}</Tag></Descriptions.Item>
            <Descriptions.Item label="项目">{String(job.project_id || "-")}</Descriptions.Item>
            <Descriptions.Item label="最佳模型">{String((metrics.best_model as Record<string, unknown> | undefined)?.name || "-")}</Descriptions.Item>
          </Descriptions>
          <Progress percent={Math.max(0, Math.min(100, percent))} status={job.status === "failed" ? "exception" : job.status === "completed" ? "success" : "active"} />
          <Text type="secondary">已完成 {Number.isFinite(completed) ? completed : 0} / {Number.isFinite(total) ? total : 0} 个模型</Text>
        </Card>
        <Card title="模型结果" extra={<Space>
          <Button type="primary" onClick={generateReport} loading={reportGenerating} disabled={!reportReady}>生成分析报告</Button>
          <Button icon={<DownloadOutlined />} onClick={exportReport} disabled={!analysisReport || !reportReady}>导出分析报告</Button>
        </Space>}>
          {rows.length === 0 ? <Empty description={job.status === "completed" ? "暂无模型结果" : "模型训练中"} /> : <Table rowKey="key" dataSource={rows} pagination={false} columns={[
            { title: "排名", key: "rank", render: (_: unknown, __: unknown, index: number) => index + 1 },
            { title: "模型", key: "name", render: (row: typeof rows[number]) => String(row.name || row.model || row.algorithm || "-") },
            { title: "AUC", dataIndex: "auc", key: "auc", sorter: (a: typeof rows[number], b: typeof rows[number]) => (b.auc ?? -1) - (a.auc ?? -1), render: (value: number | null) => value == null ? "-" : <Text strong>{value.toFixed(4)}</Text> },
            { title: "F1", dataIndex: "f1", key: "f1", render: (value: number | null) => value == null ? "-" : value.toFixed(4) },
            { title: "状态", dataIndex: "status", key: "status", render: (value: unknown) => value ? <Tag>{String(value)}</Tag> : "-" },
            { title: "操作", key: "actions", render: (_: unknown, row: typeof rows[number]) => <Button type="link" onClick={() => setSelectedModel(row)}>详细</Button> },
          ]} />}
          {analysisReport && <Text type="secondary" style={{ display: "block", marginTop: 12 }}>报告已生成：{new Date(String(analysisReport.generated_at)).toLocaleString()}</Text>}
        </Card>
        <Modal
          title={`${String(selectedModel?.name || selectedModel?.model || selectedModel?.algorithm || "模型")} 详细结果`}
          open={Boolean(selectedModel)}
          onCancel={() => setSelectedModel(null)}
          footer={null}
          width={900}
        >
          {selectedModel && <Space direction="vertical" size={14} style={{ width: "100%" }}>
            <Row gutter={[12, 12]}>
              <Col xs={24} sm={6}><Card size="small"><Statistic title="AUC" value={formatMetric(metric(selectedModel, ["auc", "AUC", "roc_auc", "rocAuc", "roc_auc_score"]))} /></Card></Col>
              <Col xs={24} sm={6}><Card size="small"><Statistic title="F1" value={formatMetric(metric(selectedModel, ["f1", "F1", "f1_score", "f1_weighted"]))} /></Card></Col>
              <Col xs={24} sm={6}><Card size="small"><Statistic title="Best Accuracy" value={Number.isFinite(Number(selectedModel.best_score ?? selectedModel.score)) ? Number(selectedModel.best_score ?? selectedModel.score).toFixed(4) : "-"} /></Card></Col>
              <Col xs={24} sm={6}><Card size="small"><Statistic title="试验次数" value={selectedTrials.length || Number(selectedModel.completed_trials) || 0} /></Card></Col>
            </Row>
            <Card size="small" title="最佳参数" styles={{ body: { padding: 12 } }}>
              <pre style={{ margin: 0, maxHeight: 180, overflow: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 12, lineHeight: 1.6 }}>
                {JSON.stringify(selectedModel.best_params || selectedModel.params || {}, null, 2)}
              </pre>
            </Card>
            <Divider style={{ margin: "2px 0 0" }} orientation="left">超参数搜索记录</Divider>
            <Table
              size="small"
              pagination={false}
              rowKey={(trial: Record<string, unknown>) => String(trial.number)}
              dataSource={selectedTrials}
              scroll={{ x: 760, y: 360 }}
              locale={{ emptyText: "暂无超参数搜索记录" }}
              columns={[
                { title: "试验", dataIndex: "number", key: "number", width: 70 },
                { title: "状态", dataIndex: "state", key: "state", width: 100, render: (value: unknown) => <Tag color={value === "complete" ? "green" : value === "pruned" ? "orange" : value === "fail" ? "red" : "default"}>{String(value || "-")}</Tag> },
                { title: "Accuracy", dataIndex: "score", key: "score", width: 100, render: (value: unknown) => Number.isFinite(Number(value)) ? Number(value).toFixed(4) : "-" },
                { title: "超参数", dataIndex: "params", key: "params", render: (value: unknown) => <Text code style={{ whiteSpace: "normal", wordBreak: "break-word" }}>{JSON.stringify(value || {})}</Text> },
                { title: "耗时", dataIndex: "duration_seconds", key: "duration", width: 90, render: (value: unknown) => Number.isFinite(Number(value)) ? `${Number(value).toFixed(2)}s` : "-" },
              ]}
            />
          </Space>}
        </Modal>
      </> : null}
    </div>
  </AppLayout>;
}
