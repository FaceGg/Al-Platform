import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Col, Descriptions, Divider, Empty, Modal, Progress, Row, Spin, Space, Statistic, Table, Tabs, Tag, Typography, message } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useNavigate, useParams } from "react-router-dom";
import apiClient, { formatApiError } from "../api/client";
import { registerAutoMLResult } from "../api/modelRegistry";
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

function rankingMetric(value: unknown, fallback: number): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Number(numeric.toFixed(4)) : fallback;
}

type AutoMLResultRow = Record<string, unknown> & {
  key: string;
  auc: number | null;
  f1: number | null;
  best_score?: number | null;
  score?: number | null;
  training_time_seconds?: number | null;
};

export default function AutoMLTaskPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [analysisReport, setAnalysisReport] = useState<Record<string, unknown> | null>(null);
  const [reportGenerating, setReportGenerating] = useState(false);
  const [selectedModel, setSelectedModel] = useState<Record<string, unknown> | null>(null);
  const [registeringAlgorithmId, setRegisteringAlgorithmId] = useState<string | null>(null);

  useEffect(() => {
    if (!taskId) return;
    let active = true;
    const load = async () => {
      try {
        const response = await apiClient.get(`/training/jobs/${taskId}`);
        if (active) {
          const nextJob = response.data || {};
          const nextMetrics = nextJob.metrics && typeof nextJob.metrics === "object" ? nextJob.metrics as Record<string, unknown> : {};
          setJob(nextJob);
          if (nextMetrics.automl_report && typeof nextMetrics.automl_report === "object") {
            setAnalysisReport(nextMetrics.automl_report as Record<string, unknown>);
          }
          setError(undefined);
        }
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
  const rows = useMemo<AutoMLResultRow[]>(() => {
    const source = resultSource(metrics);
    const mapped: AutoMLResultRow[] = source.map((row, index) => {
      return { ...row, key: String(row.id || row.name || row.model || index), auc: metric(row, ["auc", "AUC", "roc_auc", "rocAuc", "roc_auc_score"]), f1: metric(row, ["f1", "F1", "f1_score", "f1_weighted"]) };
    });
    return mapped.sort((left, right) => rankingMetric(right.auc, -1) - rankingMetric(left.auc, -1)
      || rankingMetric(right.f1, -1) - rankingMetric(left.f1, -1)
      || rankingMetric(right.best_score ?? right.score, -1) - rankingMetric(left.best_score ?? left.score, -1)
      || Number(left.training_time_seconds ?? Number.POSITIVE_INFINITY) - Number(right.training_time_seconds ?? Number.POSITIVE_INFINITY));
  }, [metrics]);

  const reportReady = String(job?.status) === "completed" && percent >= 100 && rows.length > 0;
  const formatMetric = (value: number | null) => value == null ? "-" : value.toFixed(4);
  const selectedTrials = selectedModel && Array.isArray(selectedModel.trials)
    ? selectedModel.trials as Record<string, unknown>[]
    : [];

  const registerResult = async (row: Record<string, unknown>) => {
    const projectId = String(job?.project_id || "");
    const algorithmId = String(row.algorithm_id || "");
    if (!taskId || !projectId || !algorithmId || !row.model_library_id || row.registered_model_id) return;
    setRegisteringAlgorithmId(algorithmId);
    try {
      const response = await registerAutoMLResult(projectId, taskId, algorithmId);
      setJob((current) => {
        if (!current) return current;
        const currentMetrics = (current.metrics && typeof current.metrics === "object" ? current.metrics : {}) as Record<string, unknown>;
        const update = (value: unknown) => Array.isArray(value)
          ? value.map((item) => item && typeof item === "object" && String((item as Record<string, unknown>).algorithm_id) === algorithmId
            ? { ...(item as Record<string, unknown>), registered_model_id: response.registered_model.id, model_version_id: response.version.id }
            : item)
          : value;
        return {
          ...current,
          metrics: {
            ...currentMetrics,
            algorithm_results: update(currentMetrics.algorithm_results),
            all_results: update(currentMetrics.all_results),
            best_model: currentMetrics.best_model && typeof currentMetrics.best_model === "object" && String((currentMetrics.best_model as Record<string, unknown>).algorithm_id) === algorithmId
              ? { ...(currentMetrics.best_model as Record<string, unknown>), registered_model_id: response.registered_model.id, model_version_id: response.version.id }
              : currentMetrics.best_model,
          },
        };
      });
      message.success(response.created ? "模型已注册到当前项目" : "该模型已注册");
    } catch (cause) {
      message.error(formatApiError(cause, "模型注册失败"));
    } finally {
      setRegisteringAlgorithmId(null);
    }
  };

  const requestReport = async (regenerate = false) => {
    if (!job || !reportReady) return;
    setReportGenerating(true);
    try {
      const suffix = regenerate ? "?regenerate=true" : "";
      const response = await apiClient.post(`/training/jobs/${taskId}/automl-report${suffix}`);
      setAnalysisReport(response.data || null);
      message.success("分析报告已生成");
    } catch (cause) {
      message.error(formatApiError(cause, "分析报告生成失败"));
    } finally {
      setReportGenerating(false);
    }
  };

  const generateReport = () => {
    if (!analysisReport) {
      void requestReport();
      return;
    }
    Modal.confirm({
      title: "分析报告已经生成过，是否重新生成？",
      content: "重新生成将根据当前任务结果创建一套新的详细报告制品。",
      okText: "确定",
      cancelText: "取消",
      onOk: () => requestReport(true),
    });
  };

  const exportReport = async () => {
    if (!analysisReport) return;
    try {
      const response = await apiClient.get(`/training/jobs/${taskId}/automl-report/artifacts/package`, { responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `automl-detailed-report-${taskId || "task"}.zip`;
      anchor.click();
      URL.revokeObjectURL(url);
      message.success("详细报告已导出");
    } catch (cause) {
      message.error(formatApiError(cause, "详细报告导出失败"));
    }
  };

  const reportPreview = (analysisReport?.preview && typeof analysisReport.preview === "object" ? analysisReport.preview : {}) as Record<string, unknown>;
  const overview = (reportPreview.overview && typeof reportPreview.overview === "object" ? reportPreview.overview : {}) as Record<string, unknown>;
  const reportSelection = Array.isArray(reportPreview.selection) ? reportPreview.selection as Record<string, unknown>[] : [];
  const reportImportance = Array.isArray(reportPreview.importance) ? reportPreview.importance as Record<string, unknown>[] : [];
  const reportInference = Array.isArray(reportPreview.inference) ? reportPreview.inference as Record<string, unknown>[] : [];
  const clustering = (reportPreview.clustering && typeof reportPreview.clustering === "object" ? reportPreview.clustering : {}) as Record<string, unknown>;
  const targetColumn = String((job?.params && typeof job.params === "object" ? (job.params as Record<string, unknown>).target_column : "actual") || "actual");
  const formatParams = (value: unknown) => {
    if (typeof value === "string") {
      try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value; }
    }
    return JSON.stringify(value || {}, null, 2);
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
            <Descriptions.Item label="实验">{String(job.experiment_name || "-")}</Descriptions.Item>
            <Descriptions.Item label="状态"><Tag color={job.status === "completed" ? "green" : job.status === "failed" ? "red" : "blue"}>{String(job.status || "queued")}</Tag></Descriptions.Item>
            <Descriptions.Item label="项目">{String(job.project_name || "-")}</Descriptions.Item>
            <Descriptions.Item label="最佳模型">{String((metrics.best_model as Record<string, unknown> | undefined)?.name || "-")}</Descriptions.Item>
          </Descriptions>
          <Progress percent={Math.max(0, Math.min(100, percent))} status={job.status === "failed" ? "exception" : job.status === "completed" ? "success" : "active"} />
          <Text type="secondary">已完成 {Number.isFinite(completed) ? completed : 0} / {Number.isFinite(total) ? total : 0} 个模型</Text>
        </Card>
        <Card title="模型结果" extra={<Space>
          <Button type="primary" onClick={generateReport} loading={reportGenerating} disabled={!reportReady}>生成分析报告</Button>
          <Button icon={<DownloadOutlined />} onClick={() => void exportReport()} disabled={!analysisReport || !reportReady}>导出详细报告</Button>
        </Space>}>
          {rows.length === 0 ? <Empty description={job.status === "completed" ? "暂无模型结果" : "模型训练中"} /> : <Table rowKey="key" dataSource={rows} pagination={false} columns={[
            { title: "排名", key: "rank", render: (_: unknown, __: unknown, index: number) => index + 1 },
            { title: "模型", key: "name", render: (row: typeof rows[number]) => String(row.name || row.model || row.algorithm || "-") },
            { title: "AUC", dataIndex: "auc", key: "auc", sorter: (a: typeof rows[number], b: typeof rows[number]) => (b.auc ?? -1) - (a.auc ?? -1), render: (value: number | null) => value == null ? "-" : <Text strong>{value.toFixed(4)}</Text> },
            { title: "F1", dataIndex: "f1", key: "f1", render: (value: number | null) => value == null ? "-" : value.toFixed(4) },
            { title: "状态", dataIndex: "status", key: "status", render: (value: unknown) => value ? <Tag>{String(value)}</Tag> : "-" },
            { title: "操作", key: "actions", render: (_: unknown, row: typeof rows[number]) => {
              const algorithmId = String(row.algorithm_id || "");
              const registered = Boolean(row.registered_model_id);
              const canRegister = String(row.status || "") === "completed" && Boolean(row.model_library_id);
              return <Space size={4}>
                <Button type="link" onClick={() => setSelectedModel(row)}>详细</Button>
                <Button
                  type="link"
                  disabled={!canRegister || registered}
                  loading={registeringAlgorithmId === algorithmId}
                  onClick={() => void registerResult(row)}
                >{registered ? "已注册" : "注册"}</Button>
              </Space>;
            } },
          ]} />}
        </Card>
        {analysisReport && <Card title="分析报告预览" style={{ marginTop: 16 }}>
          <Tabs items={[
            { key: "overview", label: "总览", children: <Descriptions bordered size="small" column={{ xs: 1, sm: 2, md: 3 }}>
              <Descriptions.Item label="项目">{String(overview.project || "-")}</Descriptions.Item><Descriptions.Item label="实验">{String(overview.experiment || "-")}</Descriptions.Item><Descriptions.Item label="最佳模型">{typeof overview.best_model === "object" ? String((overview.best_model as Record<string, unknown>).name || "-") : String(overview.best_model || "-")}</Descriptions.Item><Descriptions.Item label="样本数">{String(overview.rows || 0)}</Descriptions.Item><Descriptions.Item label="特征数">{String(overview.features || 0)}</Descriptions.Item><Descriptions.Item label="最优聚类 K">{String(overview.best_k || "-")}</Descriptions.Item>
            </Descriptions> },
            { key: "selection", label: "AutoML选型", children: <Table size="small" rowKey={(row) => String(row.algorithm_id || row.name)} pagination={false} dataSource={reportSelection} columns={[{ title: "算法", render: (row) => String(row.name || row.algorithm_id || "-") }, { title: "AUC", dataIndex: "AUC", render: (value) => Number.isFinite(Number(value)) ? Number(value).toFixed(4) : "-" }, { title: "F1", dataIndex: "F1", render: (value) => Number.isFinite(Number(value)) ? Number(value).toFixed(4) : "-" }, { title: "Accuracy", dataIndex: "Accuracy", render: (value) => Number.isFinite(Number(value)) ? Number(value).toFixed(4) : "-" }, { title: "最佳参数", dataIndex: "best_params", render: (value, row) => <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{formatParams(value || row.params)}</pre> }]} /> },
            { key: "clustering", label: "聚类画像", children: <Descriptions bordered size="small"><Descriptions.Item label="最优 K">{String(clustering.best_k || "-")}</Descriptions.Item><Descriptions.Item label="轮廓系数">{Number.isFinite(Number(clustering.silhouette)) ? Number(clustering.silhouette).toFixed(4) : "-"}</Descriptions.Item><Descriptions.Item label="各簇样本数">{JSON.stringify(clustering.counts || {})}</Descriptions.Item></Descriptions> },
            { key: "importance", label: "特征重要性", children: <Table size="small" rowKey={(row) => String(row.feature)} pagination={false} dataSource={[...reportImportance].sort((left, right) => Number(right.importance || 0) - Number(left.importance || 0))} columns={[{ title: "特征", dataIndex: "feature" }, { title: "重要性", dataIndex: "importance", render: (value) => Number(value).toFixed(6) }, { title: "归一化权重", dataIndex: "weight", render: (value) => Number(value).toFixed(6) }]} /> },
            { key: "inference", label: "推理结果", children: <Table size="small" rowKey={(_, index) => String(index)} pagination={{ pageSize: 10 }} dataSource={reportInference} columns={Object.keys(reportInference[0] || {}).map((key) => ({ title: key === "actual" ? targetColumn : key, dataIndex: key, key }))} /> },
          ]} />
        </Card>}
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
              <Col xs={24} sm={6}><Card size="small"><Statistic title="Accuracy" value={Number.isFinite(Number(selectedModel.best_score ?? selectedModel.accuracy ?? selectedModel.score)) ? Number(selectedModel.best_score ?? selectedModel.accuracy ?? selectedModel.score).toFixed(4) : "-"} /></Card></Col>
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
                { title: "AUC", dataIndex: "auc", key: "auc", width: 100, render: (value: unknown) => Number.isFinite(Number(value)) ? Number(value).toFixed(4) : "-" },
                { title: "F1", dataIndex: "f1", key: "f1", width: 100, render: (value: unknown) => Number.isFinite(Number(value)) ? Number(value).toFixed(4) : "-" },
                { title: "Accuracy", dataIndex: "accuracy", key: "accuracy", width: 110, render: (value: unknown, trial: Record<string, unknown>) => Number.isFinite(Number(value ?? trial.score)) ? Number(value ?? trial.score).toFixed(4) : "-" },
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
