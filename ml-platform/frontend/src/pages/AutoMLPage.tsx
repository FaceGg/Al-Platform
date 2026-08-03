import { useEffect, useState, useRef } from "react";
import { App as AntApp, Card, Select, Button, Input, Typography, Table, Row, Col, Spin, Tag, Tabs, Modal, Form, Descriptions, Space, Switch } from "antd";
import { ThunderboltOutlined, TrophyOutlined, BarChartOutlined, RadarChartOutlined, DownloadOutlined, DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import * as echarts from "echarts";
import apiClient, { formatApiError } from "../api/client";
import { getDatasetPreview, listDatasets } from "../api/datasets";
import { createQualityRun, downloadQualityArtifact, getQualityRun, type QualityRun } from "../api/spotWeldQuality";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Text, Title } = Typography;

const AUTOML_CANDIDATE_OPTIONS: Record<string, Array<{ value: string; label: string }>> = {
  classification: [
    { value: "LGB_v1", label: "LGB_v1 · LightGBM" },
    { value: "LGB_v2", label: "LGB_v2 · LightGBM" },
    { value: "XGB_v1", label: "XGB_v1 · XGBoost" },
    { value: "XGB_v2", label: "XGB_v2 · XGBoost" },
    { value: "CAT_v1", label: "CAT_v1 · CatBoost" },
    { value: "CAT_v2", label: "CAT_v2 · CatBoost" },
    { value: "GBDT_v1", label: "GBDT_v1 · GBDT" },
    { value: "RF_v1", label: "RF_v1 · Random Forest" },
    { value: "ET_v1", label: "ET_v1 · Extra Trees" },
    { value: "HGB_v1", label: "HGB_v1 · HistGradientBoosting" },
  ],
  regression: [
    { value: "LGB_v1", label: "LGB_v1 · LightGBM" },
    { value: "LGB_v2", label: "LGB_v2 · LightGBM" },
    { value: "XGB_v1", label: "XGB_v1 · XGBoost" },
    { value: "XGB_v2", label: "XGB_v2 · XGBoost" },
    { value: "CAT_v1", label: "CAT_v1 · CatBoost" },
    { value: "CAT_v2", label: "CAT_v2 · CatBoost" },
    { value: "GBDT_v1", label: "GBDT_v1 · GBDT" },
    { value: "RF_v1", label: "RF_v1 · Random Forest" },
    { value: "ET_v1", label: "ET_v1 · Extra Trees" },
    { value: "HGB_v1", label: "HGB_v1 · HistGradientBoosting" },
  ],
};

const REPORT_CANDIDATE_OPTIONS = [
  "LGB_v1", "LGB_v2", "XGB_v1", "XGB_v2", "CAT_v1",
  "CAT_v2", "GBDT_v1", "RF_v1", "ET_v1", "HGB_v1",
].map((value) => ({ value, label: value }));

const QUALITY_REQUIRED_SOURCE_COLUMNS = [
  "wld1c", "wld2c", "tipv1", "tipv2", "wres", "energy",
  "wld_spatter_strength", "wld1_spatter_strength", "wld2_spatter_strength",
  "spatterpos_wld", "spatterpos_pre", "spotdiameter", "spotposition", "spattercode",
  "cvei", "cvev", "cver", "cvep",
];

const QUALITY_CHARTS: Array<{ key: "model_comparison_chart" | "cluster_pca_chart" | "feature_importance_chart" | "warning_distribution_chart" | "waveform_comparison_chart"; label: string }> = [
  { key: "model_comparison_chart", label: "AutoML模型对比图" },
  { key: "cluster_pca_chart", label: "聚类PCA可视化图" },
  { key: "feature_importance_chart", label: "特征重要性Top20图" },
  { key: "warning_distribution_chart", label: "缺陷预警分布图" },
  { key: "waveform_comparison_chart", label: "正常vs缺陷波形对比图" },
];

interface ModelingTask {
  id: string;
  project_id?: string;
  name?: string;
  status?: string;
  kind: "ordinary" | "spot-weld";
  created_at?: string;
  progress: { completed: number; total: number; percent: number };
  errorCode?: string;
  errorMessage?: string;
}

function normalizeProgress(value: unknown): ModelingTask["progress"] {
  const source = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const completed = Number(source.completed ?? source.completed_count ?? source.current ?? 0);
  const total = Number(source.total ?? source.total_count ?? source.candidates ?? 0);
  const percent = Number.isFinite(Number(source.percent))
    ? Number(source.percent)
    : total > 0 ? Math.round((completed / total) * 10000) / 100 : 0;
  return {
    completed: Number.isFinite(completed) ? completed : 0,
    total: Number.isFinite(total) ? total : 0,
    percent: Number.isFinite(percent) ? percent : 0,
  };
}

function errorMessage(value: unknown): string | undefined {
  if (!value || typeof value !== "object") return undefined;
  const message = (value as Record<string, unknown>).message;
  return typeof message === "string" && message.trim() ? message : undefined;
}

export default function AutoMLPage() {
  const { t } = useI18n();
  const { message } = AntApp.useApp();
  const [projects, setProjects] = useState<any[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [experiments, setExperiments] = useState<any[]>([]);
  const [selectedExperiment, setSelectedExperiment] = useState<string | null>(null);
  const [datasets, setDatasets] = useState<any[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);
  const [datasetColumns, setDatasetColumns] = useState<string[]>([]);
  const [numericInputColumns, setNumericInputColumns] = useState<string[]>([]);
  const [inputColumns, setInputColumns] = useState<string[]>([]);
  const [targetColumn, setTargetColumn] = useState("");
  const [taskType, setTaskType] = useState("classification");
  const [candidateIds, setCandidateIds] = useState<string[]>([]);
  const [crossValidationEnabled, setCrossValidationEnabled] = useState(true);
  const [crossValidationFolds, setCrossValidationFolds] = useState<3 | 4 | 5>(5);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<any>(null);
  const [activeTab, setActiveTab] = useState("results");
  const [recipeTab, setRecipeTab] = useState("general");
  const [qualityRunning, setQualityRunning] = useState(false);
  const [qualityCandidateIds, setQualityCandidateIds] = useState<string[]>([]);
  const [qualityTargetColumn, setQualityTargetColumn] = useState("");
  const [qualityInputColumns, setQualityInputColumns] = useState<string[]>([]);
  const [qualityCrossValidationEnabled, setQualityCrossValidationEnabled] = useState(true);
  const [qualityCrossValidationFolds, setQualityCrossValidationFolds] = useState<3 | 4 | 5>(3);
  const [qualityRun, setQualityRun] = useState<QualityRun | null>(null);
  const [downloadingQualityReport, setDownloadingQualityReport] = useState(false);
  const [modelingTasks, setModelingTasks] = useState<ModelingTask[]>([]);
  const [loadingModelingTasks, setLoadingModelingTasks] = useState(false);
  const [qualityChartUrls, setQualityChartUrls] = useState<Record<string, string>>({});
  const [experimentModalOpen, setExperimentModalOpen] = useState(false);
  const [experimentCreating, setExperimentCreating] = useState(false);
  const [experimentForm] = Form.useForm();
  const barRef = useRef<HTMLDivElement>(null);
  const radarRef = useRef<HTMLDivElement>(null);
  const qualityMissingSourceColumns = QUALITY_REQUIRED_SOURCE_COLUMNS.filter(
    (column) => !datasetColumns.includes(column),
  );
  const qualityTargetColumns = datasetColumns.filter(
    (column) => !QUALITY_REQUIRED_SOURCE_COLUMNS.includes(column),
  );
  const normalizeQualityInputColumns = (columns: string[], target = qualityTargetColumn) => {
    const allowed = columns.filter((column) => datasetColumns.includes(column) && column !== target);
    const required = QUALITY_REQUIRED_SOURCE_COLUMNS.filter(
      (column) => datasetColumns.includes(column) && column !== target,
    );
    return Array.from(new Set([...required, ...allowed]));
  };

  const refreshModelingTasks = async () => {
    if (!selectedProject) {
      setModelingTasks([]);
      return;
    }
    setLoadingModelingTasks(true);
    try {
      const [ordinaryResponse, qualityResponse] = await Promise.all([
        apiClient.get("/training/automl/jobs", { params: { project_id: selectedProject } }),
        apiClient.get(`/projects/${selectedProject}/spot-weld/runs`),
      ]);
      const ordinaryItems = Array.isArray(ordinaryResponse.data)
        ? ordinaryResponse.data
        : ordinaryResponse.data?.items || [];
      const qualityItems = Array.isArray(qualityResponse.data)
        ? qualityResponse.data
        : qualityResponse.data?.items || [];
      const tasks: ModelingTask[] = [
        ...ordinaryItems
          .filter((job: Record<string, unknown>) => String(job.project_id || selectedProject) === selectedProject)
          .map((job: Record<string, unknown>) => ({
          id: String(job.id),
          project_id: String(job.project_id || selectedProject),
          name: String(job.name || "AutoML"),
          status: String(job.status || "queued"),
          kind: "ordinary" as const,
          created_at: typeof job.created_at === "string" ? job.created_at : undefined,
          progress: normalizeProgress((job.metrics as Record<string, unknown> | undefined)?.progress || job.progress),
          errorCode: typeof job.error_code === "string" ? job.error_code : undefined,
          errorMessage: errorMessage(job.error_details),
          })),
        ...qualityItems.map((run: Record<string, unknown>) => ({
          id: String(run.id),
          project_id: String(run.project_id || selectedProject),
          name: "点焊质量感知",
          status: String(run.status || "queued"),
          kind: "spot-weld" as const,
          created_at: typeof run.created_at === "string" ? run.created_at : undefined,
          progress: normalizeProgress(
            (run.statistics as Record<string, unknown> | undefined)?.modeling_progress || run.modeling_progress,
          ),
          errorCode: typeof run.error_code === "string" ? run.error_code : undefined,
          errorMessage: errorMessage(run.error_details),
        })),
      ];
      tasks.sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")));
      setModelingTasks(tasks);
    } catch (error) {
      message.error(formatApiError(error, "建模任务加载失败"));
    } finally {
      setLoadingModelingTasks(false);
    }
  };

  const deleteModelingTask = async (task: ModelingTask) => {
    if (!selectedProject) return;
    try {
      if (task.kind === "spot-weld") {
        await apiClient.delete(`/projects/${selectedProject}/spot-weld/runs/${task.id}`);
      } else {
        await apiClient.post("/training/batch-delete", { ids: [task.id] });
      }
      message.success("建模任务已删除");
      await refreshModelingTasks();
    } catch (error) {
      message.error(formatApiError(error, "建模任务删除失败"));
    }
  };

  useEffect(() => {
    apiClient.get("/projects").then((res) => setProjects(res.data.items || res.data || [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedProject) {
      setDatasets([]); setSelectedDataset(null);
      setExperiments([]); setSelectedExperiment(null);
      setModelingTasks([]);
      return;
    }
    listDatasets(selectedProject).then(setDatasets).catch(() => setDatasets([]));
    apiClient.get("/experiments", { params: { project_id: selectedProject } })
      .then((res) => {
        const items = res.data.items || [];
        setExperiments(items);
        setSelectedExperiment(items[0]?.id || null);
      })
      .catch(() => { setExperiments([]); setSelectedExperiment(null); });
    void refreshModelingTasks();
  }, [selectedProject]);

  useEffect(() => {
    if (!selectedProject || !modelingTasks.some((task) => ["queued", "validating", "running", "pending"].includes(String(task.status)))) return;
    const timer = window.setInterval(() => { void refreshModelingTasks(); }, 1500);
    return () => window.clearInterval(timer);
  }, [selectedProject, modelingTasks]);

  useEffect(() => {
    if (!selectedDataset) {
      setDatasetColumns([]);
      setNumericInputColumns([]);
      setInputColumns([]);
      setTargetColumn("");
      setQualityInputColumns([]);
      setQualityTargetColumn("");
      return;
    }
    // Do not let a previous dataset schema authorize a run while the new preview is loading.
    setDatasetColumns([]);
    setNumericInputColumns([]);
    setInputColumns([]);
    setTargetColumn("");
    setQualityInputColumns([]);
    setQualityTargetColumn("");
    getDatasetPreview(selectedDataset)
      .then((data) => {
        const columns: string[] = Array.isArray(data.columns)
          ? data.columns.filter((column: unknown): column is string => typeof column === "string")
          : [];
        const dtypes = data.dtypes && typeof data.dtypes === "object" ? data.dtypes : {};
        setDatasetColumns(columns);
        setNumericInputColumns(columns.filter((column) => /^(?:u?int|float|complex)/i.test(String(dtypes[column] || ""))));
        setTargetColumn((current) => columns.includes(current) ? current : (columns.includes("label") ? "label" : ""));
        setQualityTargetColumn((current) => (
          columns.includes(current) && !QUALITY_REQUIRED_SOURCE_COLUMNS.includes(current) ? current : ""
        ));
      })
      .catch(() => { setDatasetColumns([]); setNumericInputColumns([]); setInputColumns([]); message.error(t.common.error); });
  }, [selectedDataset, t.common.error, message]);

  useEffect(() => {
    const allowed = numericInputColumns.filter((column) => column !== targetColumn);
    setInputColumns((current) => {
      const retained = current.filter((column) => allowed.includes(column));
      return retained.length ? retained : allowed;
    });
  }, [numericInputColumns, targetColumn]);

  useEffect(() => {
    setQualityInputColumns((current) => {
      return normalizeQualityInputColumns(current);
    });
  }, [datasetColumns, qualityTargetColumn]);

  const allResults = results?.models || results?.all_results || [];
  const bestModel = results?.best_model || allResults[0];
  const features = results?.feature_importance || results?.features || {};
  const candidateOptions = AUTOML_CANDIDATE_OPTIONS[taskType] || [];

  const handleTaskTypeChange = (task: string) => {
    const validCandidateIds = new Set(
      (AUTOML_CANDIDATE_OPTIONS[task] || []).map((candidate) => candidate.value),
    );
    setTaskType(task);
    setCandidateIds((current) => current.filter((candidateId) => validCandidateIds.has(candidateId)));
  };

  useEffect(() => {
    if (!results || allResults.length === 0) return;

    // Bar chart
    if (barRef.current) {
      const chart = echarts.init(barRef.current);
      const names = allResults.map((r: any) => r.name || r.model || "Unknown");
      const scores = allResults.map((r: any) => r.score != null ? Number(r.score) : 0);
      chart.setOption({
        title: { text: t.automl?.all_results || "Model Comparison", left: "center", textStyle: { fontSize: 14 } },
        tooltip: { trigger: "axis" },
        xAxis: { type: "category", data: names, axisLabel: { rotate: 30 } },
        yAxis: { type: "value", name: t.automl?.score || "Score" },
        series: [{
          type: "bar", data: scores.map((v: number, i: number) => ({
            value: v,
            itemStyle: { color: names[i] === (bestModel?.name || bestModel?.model) ? "#52c41a" : "#1890ff" }
          })),
          label: { show: true, position: "top", formatter: (p: any) => p.value.toFixed(4) }
        }],
        grid: { top: 40, bottom: 60 },
      });
      setTimeout(() => chart.resize(), 100);
      return () => chart.dispose();
    }
  }, [results]);

  // Radar chart
  useEffect(() => {
    if (!results || allResults.length < 2) return;
    if (radarRef.current) {
      const chart = echarts.init(radarRef.current);
      const modelNames = allResults.map((r: any) => r.name || r.model || "Unknown");
      const maxScore = Math.max(...allResults.map((r: any) => r.score || 0));
      chart.setOption({
        title: { text: "Model Radar", left: "center", textStyle: { fontSize: 14 } },
        tooltip: {},
        legend: { data: modelNames, bottom: 0 },
        radar: {
          indicator: [
            { name: "Accuracy", max: maxScore || 1 },
            { name: "Precision", max: maxScore || 1 },
            { name: "Recall", max: maxScore || 1 },
            { name: "F1", max: maxScore || 1 },
            { name: "AUC", max: maxScore || 1 },
          ],
        },
        series: [{
          type: "radar",
          data: allResults.map((r: any) => ({
            name: r.name || r.model || "Unknown",
            value: Array(5).fill(Number(r.score || 0)),
          })),
        }],
      });
      setTimeout(() => chart.resize(), 100);
      return () => chart.dispose();
    }
  }, [results]);

  const handleRun = async () => {
    if (!selectedProject || !selectedExperiment || !selectedDataset || !targetColumn || inputColumns.length === 0) {
      message.warning((t.automl?.select_project || "Project") + " / " + (t.automl?.select_dataset || "Dataset") + " / " + (t.automl?.target || "Target"));
      return;
    }
    setRunning(true);
    setResults(null);
    try {
      const res = await apiClient.post("/training/automl/run", {
        project_id: selectedProject, experiment_id: selectedExperiment,
        dataset_artifact_id: selectedDataset, target_column: targetColumn,
        input_columns: inputColumns,
        task: taskType,
        candidate_ids: candidateIds,
        cross_validation_enabled: crossValidationEnabled,
        cross_validation_folds: crossValidationEnabled ? crossValidationFolds : null,
      });
      void refreshModelingTasks();
      const rid = res.data.run_id || res.data.id || res.data.job_id;
      const poll = setInterval(async () => {
        try {
          const r = await apiClient.get("/training/jobs/" + rid);
          const d = r.data;
          if (d.status === "completed" || d.status === "done") {
            clearInterval(poll); setResults(d.metrics || d); setRunning(false); void refreshModelingTasks(); message.success(t.common.success);
          } else if (d.status === "failed") {
            clearInterval(poll); setRunning(false); void refreshModelingTasks(); message.error(t.common.error);
          }
        } catch { /* continue */ }
      }, 3000);
    } catch (e: any) {
      message.error(formatApiError(e, t.common.error));
      setRunning(false);
    }
  };

  const createExperiment = async (values: { name: string; description?: string }) => {
    if (!selectedProject) return;
    setExperimentCreating(true);
    try {
      const response = await apiClient.post("/experiments", {
        project_id: selectedProject,
        name: values.name,
        description: values.description || "",
      });
      const experiment = response.data;
      setExperiments((items) => [experiment, ...items]);
      setSelectedExperiment(experiment.id);
      experimentForm.resetFields();
      setExperimentModalOpen(false);
      message.success(t.common.success);
    } catch (error: any) {
      message.error(error.response?.data?.detail?.message || error.response?.data?.detail || t.common.error);
    } finally {
      setExperimentCreating(false);
    }
  };

  const handleQualityRun = async () => {
    if (!selectedProject || !selectedDataset) {
      message.warning("请选择项目、点焊报告数据和输入列");
      return;
    }
    if (qualityMissingSourceColumns.length > 0) {
      message.error(`当前数据不符合点焊质量感知格式，缺少：${qualityMissingSourceColumns.join("、")}`);
      return;
    }
    const normalizedInputs = normalizeQualityInputColumns(qualityInputColumns);
    if (normalizedInputs.length === 0) {
      message.warning("请选择项目、点焊报告数据和输入列");
      return;
    }
    setQualityRunning(true);
    try {
      const run = await createQualityRun(selectedProject, {
        dataset_artifact_id: selectedDataset,
        field_mapping: {},
        candidate_ids: qualityCandidateIds,
        target_column: qualityTargetColumn || undefined,
        input_columns: normalizedInputs,
        cross_validation_enabled: qualityCrossValidationEnabled,
        cross_validation_folds: qualityCrossValidationEnabled ? qualityCrossValidationFolds : null,
      });
      setQualityRun(run);
      void refreshModelingTasks();
      message.success("点焊质量运行已创建");
    } catch (error: any) {
      message.error(error.response?.data?.detail?.message || error.response?.data?.detail || t.common.error);
    } finally {
      setQualityRunning(false);
    }
  };

  useEffect(() => {
    if (!selectedProject || !qualityRun || !["queued", "validating", "running"].includes(String(qualityRun.status))) return;
    let active = true;
    const refreshQualityRun = async () => {
      try {
        const latest = await getQualityRun(selectedProject, qualityRun.id);
        if (active) {
          setQualityRun(latest);
          void refreshModelingTasks();
        }
      } catch {
        // Annotation workspace remains the recovery path when a queued task is no longer readable.
      }
    };
    void refreshQualityRun();
    const timer = window.setInterval(() => { void refreshQualityRun(); }, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [qualityRun?.id, qualityRun?.status, selectedProject]);

  useEffect(() => {
    let active = true;
    const artifacts = qualityRun?.output_artifacts || {};
    if (!selectedProject || qualityRun?.status !== "completed") {
      setQualityChartUrls({});
      return () => { active = false; };
    }
    const available = QUALITY_CHARTS.filter(({ key }) => artifacts[key]);
    if (available.length === 0) {
      setQualityChartUrls({});
      return () => { active = false; };
    }
    void Promise.all(available.map(async ({ key }) => {
      try {
        const blob = await downloadQualityArtifact(selectedProject, qualityRun.id, key);
        if (typeof URL.createObjectURL !== "function") return [key, ""] as const;
        return [key, URL.createObjectURL(blob)] as const;
      } catch {
        return [key, ""] as const;
      }
    })).then((entries) => {
      if (!active) return;
      setQualityChartUrls(Object.fromEntries(entries.filter(([, url]) => url)));
    });
    return () => { active = false; };
  }, [qualityRun?.id, qualityRun?.status, qualityRun?.output_artifacts, selectedProject]);

  const downloadQualityReport = async () => {
    if (!selectedProject || !qualityRun?.id || !qualityRun.output_artifacts?.report) return;
    setDownloadingQualityReport(true);
    try {
      const blob = await downloadQualityArtifact(selectedProject, qualityRun.id, "report");
      if (typeof URL.createObjectURL !== "function") return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `spot-weld-quality-report-${qualityRun.id.slice(0, 8)}.xlsx`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      message.error(formatApiError(error, "质量报告下载失败"));
    } finally {
      setDownloadingQualityReport(false);
    }
  };

  const resultColumns = [
    { title: t.knowledge?.name || "Name", dataIndex: "name", key: "name" },
    { title: t.automl?.score || "Score", dataIndex: "score", key: "score", render: (v: number) => v != null ? Number(v).toFixed(4) : "-" },
    { title: "Task", dataIndex: "task_type", key: "task" },
    {
      title: "Time",
      key: "time",
      render: (_value: unknown, row: { training_time_seconds?: number | null; training_time?: number | null }) => {
        const value = row.training_time_seconds ?? row.training_time;
        return value != null ? `${Number(value).toFixed(1)}s` : "-";
      },
    },
  ];

  const featureEntries = Object.entries(features).sort((a: any, b: any) => b[1] - a[1]);
  const maxImp = featureEntries.length > 0 ? (featureEntries[0][1] as number) : 1;
  const qualityCandidates = Array.isArray(qualityRun?.automl_results) ? qualityRun.automl_results : [];
  const qualityCluster = qualityRun?.clustering_results || {};
  const qualityKSearch = Object.entries((qualityCluster.silhouette_scores || {}) as Record<string, number>);
  const qualityPca = Array.isArray(qualityCluster.pca_coordinates) ? qualityCluster.pca_coordinates : [];
  const qualityBestCandidate = qualityCandidates.find((candidate) => candidate.error_code == null) || qualityCandidates[0];
  const formatQualityMetric = (key: string) => {
    const value = qualityBestCandidate?.[key];
    return typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : "-";
  };
  const qualityCandidateColumns = [
    { title: "候选模型", dataIndex: "name", key: "name" },
    { title: "AUC", dataIndex: "auc", key: "auc", render: (value: number | null) => value == null ? "-" : Number(value).toFixed(4) },
    { title: "F1", dataIndex: "f1", key: "f1", render: (value: number | null) => value == null ? "-" : Number(value).toFixed(4) },
    { title: "训练耗时", dataIndex: "training_time_seconds", key: "time", render: (value: number | null) => value == null ? "-" : `${Number(value).toFixed(1)}s` },
  ];
  const modelingTaskColumns = [
    { title: "任务", dataIndex: "name", key: "name", render: (value: string, row: ModelingTask) => <Space size={6}><strong>{value}</strong><Tag color={row.kind === "spot-weld" ? "blue" : "default"}>{row.kind === "spot-weld" ? "点焊建模" : "普通建模"}</Tag></Space> },
    { title: "状态", dataIndex: "status", key: "status", render: (value: string) => <Tag color={value === "completed" ? "green" : value === "failed" ? "red" : "blue"}>{value}</Tag> },
    { title: "建模进度", key: "progress", render: (_value: unknown, row: ModelingTask) => `${row.progress.completed}/${row.progress.total} ${row.progress.percent}%` },
    { title: "错误详情", key: "error", render: (_value: unknown, row: ModelingTask) => (row.errorCode || row.errorMessage) ? <Space direction="vertical" size={0}><Text type="danger">{row.errorCode}</Text>{row.errorMessage && <Text type="danger">{row.errorMessage}</Text>}</Space> : "-" },
    { title: "操作", key: "actions", render: (_value: unknown, row: ModelingTask) => <Button type="text" danger icon={<DeleteOutlined />} aria-label={`删除建模任务 ${row.id}`} onClick={() => void deleteModelingTask(row)} disabled={!['completed', 'failed', 'cancelled'].includes(String(row.status))}>删除</Button> },
  ];

  return (
    <AppLayout>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <h3>{t.automl?.title || "AutoML"}</h3>
        <Button icon={<PlusOutlined />} aria-label="新建" onClick={() => { setRecipeTab("general"); setResults(null); }}>新建</Button>
      </div>
      {selectedProject && <Card title="建模任务" style={{ marginBottom: 16 }} extra={<Button type="link" onClick={() => void refreshModelingTasks()} loading={loadingModelingTasks}>刷新</Button>}>
        <Table<ModelingTask> rowKey={(task) => `${task.kind}-${task.id}`} size="small" columns={modelingTaskColumns} dataSource={modelingTasks} loading={loadingModelingTasks} pagination={false} locale={{ emptyText: "暂无建模任务" }} />
      </Card>}
      <Tabs
        activeKey={recipeTab}
        onChange={setRecipeTab}
        items={[
          { key: "general", label: t.automl?.title || "AutoML" },
          { key: "spot-weld-quality", label: "点焊质量感知" },
        ]}
      />
      {recipeTab === "general" && <>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]} align="middle">
          <Col xs={24} sm={6}><Text strong>{t.automl?.select_project || "Project"}</Text>
            <Select style={{ width: "100%", marginTop: 4 }} placeholder={t.automl?.select_project} value={selectedProject} onChange={setSelectedProject}
              options={projects.map((p: any) => ({ value: p.id, label: p.name }))} /></Col>
          <Col xs={24} sm={6}><Text strong>{t.automl?.select_dataset || "Dataset"}</Text>
            <Select style={{ width: "100%", marginTop: 4 }} placeholder={t.automl?.select_dataset} value={selectedDataset} onChange={setSelectedDataset}
              options={datasets.map((d: any) => ({ value: d.id, label: d.name || d.filename }))} /></Col>
          <Col xs={24} sm={4}><Text strong>{t.training?.experiments || "Experiment"}</Text>
            <Select style={{ width: "100%", marginTop: 4 }} value={selectedExperiment || undefined} onChange={setSelectedExperiment}
              disabled={!selectedProject} placeholder={t.training?.experiments || "Experiment"}
              options={experiments.map((item: any) => ({ value: item.id, label: item.name }))} />
            <Button type="link" size="small" style={{ padding: 0, marginTop: 3 }} disabled={!selectedProject}
              onClick={() => setExperimentModalOpen(true)}>
              {t.training?.new_experiment || "New Experiment"}
            </Button>
          </Col>
          <Col xs={24} sm={4}><Text strong>{t.automl?.target || "Target"}</Text>
            <Select aria-label="目标列" style={{ width: "100%", marginTop: 4 }} placeholder={t.automl?.target} value={targetColumn || undefined} onChange={setTargetColumn}
              disabled={!selectedDataset} options={datasetColumns.map((column) => ({ value: column, label: column }))} /></Col>
          <Col xs={24} sm={6}><Text strong>输入列</Text>
            <Select
              aria-label="输入列"
              mode="multiple"
              allowClear
              maxTagCount="responsive"
              style={{ width: "100%", marginTop: 4 }}
              placeholder="选择数值输入列"
              value={inputColumns}
              onChange={(columns: string[]) => setInputColumns(columns.filter((column) => column !== targetColumn))}
              disabled={!selectedDataset}
              options={numericInputColumns.filter((column) => column !== targetColumn).map((column) => ({ value: column, label: column }))}
            /></Col>
          <Col xs={24} sm={4}><Text strong>{t.automl?.task || "Task"}</Text>
            <Select aria-label="任务类型" style={{ width: "100%", marginTop: 4 }} value={taskType} onChange={handleTaskTypeChange}
              options={[{ value: "classification", label: "Classification" }, { value: "regression", label: "Regression" }]} /></Col>
          <Col xs={24} sm={4}><Text strong>算法集合</Text>
            <Select
              aria-label="算法集合"
              mode="multiple"
              allowClear
              style={{ width: "100%", marginTop: 4 }}
              placeholder="默认全部算法"
              value={candidateIds}
              onChange={(ids: string[]) => setCandidateIds(ids)}
              options={candidateOptions}
            /></Col>
          <Col xs={12} sm={3}><Text strong>交叉验证</Text>
            <div style={{ marginTop: 7 }}><Switch aria-label="启用交叉验证" checked={crossValidationEnabled} onChange={setCrossValidationEnabled} /></div></Col>
          <Col xs={12} sm={3}><Text strong>折数</Text>
            <Select
              aria-label="交叉验证折数"
              style={{ width: "100%", marginTop: 4 }}
              value={crossValidationFolds}
              disabled={!crossValidationEnabled}
              onChange={(folds: 3 | 4 | 5) => setCrossValidationFolds(folds)}
              options={[3, 4, 5].map((folds) => ({ value: folds, label: `${folds} 折` }))}
            /></Col>
          <Col xs={24} sm={2}><Button type="primary" icon={<ThunderboltOutlined />} onClick={handleRun} loading={running} block style={{ marginTop: 22 }}>{t.automl?.run || "Run"}</Button></Col>
        </Row>
      </Card>

      {running && <Card style={{ textAlign: "center", padding: 40 }}><Spin size="large" /><p style={{ marginTop: 16 }}>{t.common.loading}</p></Card>}

      {results && (
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          { key: "results", label: "Results",
            children: (<>
              {bestModel && (
                <Card style={{ marginBottom: 16 }}>
                  <Row gutter={16}>
                    <Col span={12}>
                      <div style={{ textAlign: "center", padding: 24 }}>
                        <TrophyOutlined style={{ fontSize: 48, color: "#faad14" }} />
                        <Title level={4}>Best: {bestModel.name || bestModel.model}</Title>
                        <Title level={3} style={{ color: "#52c41a" }}>Score: {bestModel.score != null ? Number(bestModel.score).toFixed(4) : "-"}</Title>
                      </div>
                    </Col>
                    <Col span={12}>
                      <Text strong>{t.automl?.all_results || "All Results"}</Text>
                      <Table rowKey="name" dataSource={allResults} columns={resultColumns} size="small" pagination={false} style={{ marginTop: 8 }} />
                    </Col>
                  </Row>
                </Card>
              )}
              {featureEntries.length > 0 && (
                <Card title={<><BarChartOutlined /> Feature Importance</>} style={{ marginBottom: 16 }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 600 }}>
                    {featureEntries.map(([name, imp]: [string, any]) => (
                      <div key={name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <Text style={{ width: 160, textAlign: "right", fontSize: 12 }} ellipsis>{name}</Text>
                        <div style={{ flex: 1, background: "#f0f0f0", borderRadius: 4, height: 20, overflow: "hidden" }}>
                          <div style={{ width: Math.max(((imp as number) / maxImp) * 100, 2) + "%", height: "100%", background: "linear-gradient(90deg, #1890ff, #52c41a)", borderRadius: 4 }} /></div>
                        <Text style={{ width: 60, fontSize: 12 }}>{(imp as number).toFixed(4)}</Text>
                      </div>))}
                  </div>
                </Card>
              )}
            </>),
          },
          { key: "compare", label: "Compare",
            children: (
              <Row gutter={16}>
                <Col span={12}><Card><div ref={barRef} style={{ width: "100%", height: 350 }} /></Card></Col>
                <Col span={12}><Card><div ref={radarRef} style={{ width: "100%", height: 350 }} /></Card></Col>
              </Row>
            ),
          },
        ]} />
      )}
      <Modal
        title={t.training?.new_experiment || "New Experiment"}
        open={experimentModalOpen}
        onCancel={() => setExperimentModalOpen(false)}
        onOk={() => experimentForm.submit()}
        confirmLoading={experimentCreating}
      >
        <Form form={experimentForm} layout="vertical" onFinish={createExperiment}>
          <Form.Item name="name" label={t.training?.experiment_name || "Experiment Name"} rules={[{ required: true }]}>
            <Input autoFocus />
          </Form.Item>
          <Form.Item name="description" label={t.training?.description || "Description"}>
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
      </>}
      {recipeTab === "spot-weld-quality" && <section className="spot-weld-recipe">
        <Card>
          <Row gutter={[16, 16]} align="middle">
            <Col xs={24} md={5}>
              <Text strong>项目</Text>
              <Select
                aria-label="质量感知项目"
                style={{ width: "100%", marginTop: 4 }}
                value={selectedProject}
                onChange={setSelectedProject}
                placeholder="选择项目"
                options={projects.map((project: any) => ({ value: project.id, label: project.name }))}
              />
            </Col>
            <Col xs={24} md={5}>
              <Text strong>报告数据</Text>
              <Select
                aria-label="质量感知数据"
                style={{ width: "100%", marginTop: 4 }}
                value={selectedDataset}
                onChange={setSelectedDataset}
                disabled={!selectedProject}
                placeholder="CSV / XLS / XLSX"
                options={datasets.filter((dataset: any) => ["csv", "xls", "xlsx"].includes(String(dataset.format || "").toLowerCase())).map((dataset: any) => {
                  const schemaColumns = Array.isArray(dataset.schema)
                    ? dataset.schema.map((field: any) => field?.name).filter((field: unknown): field is string => typeof field === "string")
                    : [];
                  const missingColumns = schemaColumns.length
                    ? QUALITY_REQUIRED_SOURCE_COLUMNS.filter((column) => !schemaColumns.includes(column))
                    : [];
                  return {
                    value: dataset.id,
                    label: missingColumns.length ? `${dataset.name || dataset.filename}（缺少点焊字段）` : (dataset.name || dataset.filename),
                    disabled: missingColumns.length > 0,
                  };
                })}
              />
              {selectedDataset && qualityMissingSourceColumns.length > 0 && <Text type="danger" style={{ display: "block", marginTop: 6 }}>当前数据缺少点焊必需字段：{qualityMissingSourceColumns.join("、")}</Text>}
            </Col>
            <Col xs={24} md={4}>
              <Text strong>目标列（可选）</Text>
              <Select
                aria-label="质量感知目标列"
                allowClear
                style={{ width: "100%", marginTop: 4 }}
                value={qualityTargetColumn || undefined}
                onChange={(column: string | undefined) => setQualityTargetColumn(column || "")}
                disabled={!selectedDataset || qualityTargetColumns.length === 0}
                placeholder="可选监督标签"
                options={qualityTargetColumns.map((column) => ({ value: column, label: column }))}
              />
              {selectedDataset && qualityTargetColumns.length === 0 && <Text type="secondary" style={{ display: "block", marginTop: 6 }}>未检测到标签列，将使用自动标注。</Text>}
            </Col>
            <Col xs={24} md={10}>
              <Text strong>输入列</Text>
              <Select
                aria-label="质量感知输入列"
                mode="multiple"
                allowClear
                maxTagCount="responsive"
                style={{ width: "100%", marginTop: 4 }}
                value={qualityInputColumns}
                onChange={(columns: string[]) => setQualityInputColumns(normalizeQualityInputColumns(columns))}
                disabled={!selectedDataset || qualityMissingSourceColumns.length > 0}
                placeholder="已固定包含点焊必需字段，可增选其他列"
                options={datasetColumns.filter((column) => column !== qualityTargetColumn).map((column) => ({ value: column, label: column }))}
              />
            </Col>
          </Row>
          <Row gutter={[16, 16]} align="middle" style={{ marginTop: 16 }}>
            <Col xs={24} md={8}>
              <Text strong>报告候选算法</Text>
              <Select
                mode="multiple"
                aria-label="报告候选算法"
                style={{ width: "100%", marginTop: 4 }}
                value={qualityCandidateIds}
                onChange={setQualityCandidateIds}
                placeholder="留空使用全部 10 项"
                options={REPORT_CANDIDATE_OPTIONS}
              />
            </Col>
            <Col xs={12} md={4}>
              <Text strong>交叉验证</Text>
              <div style={{ marginTop: 7 }}><Switch aria-label="质量感知启用交叉验证" checked={qualityCrossValidationEnabled} onChange={setQualityCrossValidationEnabled} /></div>
            </Col>
            <Col xs={12} md={4}>
              <Text strong>折数</Text>
              <Select
                aria-label="质量感知交叉验证折数"
                style={{ width: "100%", marginTop: 4 }}
                value={qualityCrossValidationFolds}
                disabled={!qualityCrossValidationEnabled}
                onChange={(folds: 3 | 4 | 5) => setQualityCrossValidationFolds(folds)}
                options={[3, 4, 5].map((folds) => ({ value: folds, label: `${folds} 折` }))}
              />
            </Col>
            <Col xs={24} md={4}>
              <Button type="primary" icon={<ThunderboltOutlined />} aria-label="运行质量感知" onClick={() => void handleQualityRun()} loading={qualityRunning} disabled={!selectedProject || !selectedDataset || qualityInputColumns.length === 0 || qualityMissingSourceColumns.length > 0} block style={{ marginTop: 22 }}>运行质量感知</Button>
            </Col>
          </Row>
        </Card>
        {qualityRun && <Card style={{ marginTop: 16 }}>
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
              <Descriptions.Item label="运行"><Tag color={qualityRun.status === "completed" ? "green" : qualityRun.status === "failed" ? "red" : "blue"}>{qualityRun.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="样本">{qualityRun.sample_count ?? "-"}</Descriptions.Item>
              <Descriptions.Item label="特征版本">{qualityRun.feature_version || "report_v1"}</Descriptions.Item>
              <Descriptions.Item label="聚类 K">{String(qualityCluster.best_k ?? "-")}</Descriptions.Item>
              <Descriptions.Item label="K 搜索">{qualityKSearch.length ? qualityKSearch.map(([k, score]) => `K=${k}: ${Number(score).toFixed(3)}`).join(" · ") : "-"}</Descriptions.Item>
              <Descriptions.Item label="PCA">{qualityPca.length ? `${qualityPca.length} x 2` : "-"}</Descriptions.Item>
              {qualityRun.status === "failed" && <Descriptions.Item label="错误详情" span={4}><Space direction="vertical" size={0}><Text type="danger">{qualityRun.error_code || "QUALITY_RUN_FAILED"}</Text>{qualityRun.error_details?.message && <Text type="danger">{qualityRun.error_details.message}</Text>}</Space></Descriptions.Item>}
            </Descriptions>
            {qualityCandidates.length > 0 && <Table rowKey={(row: any) => row.name} size="small" columns={qualityCandidateColumns} dataSource={qualityCandidates} pagination={false} scroll={{ x: 600 }} />}
            {qualityRun.status === "completed" && <Card size="small" title="主要报告">
              <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
                <Descriptions.Item label="评估">{qualityRun.evaluation?.cross_validation_enabled ? `${qualityRun.evaluation.cross_validation_folds} 折交叉验证` : "固定留出集"}</Descriptions.Item>
                <Descriptions.Item label="目标列">{qualityRun.target_column || "未选择"}</Descriptions.Item>
                <Descriptions.Item label="最佳 AUC">{formatQualityMetric("auc")}</Descriptions.Item>
                <Descriptions.Item label="最佳 F1">{formatQualityMetric("f1")}</Descriptions.Item>
              </Descriptions>
              <Space style={{ marginTop: 12 }}>
                <Button icon={<DownloadOutlined />} aria-label="下载完整报告" onClick={() => void downloadQualityReport()} loading={downloadingQualityReport} disabled={!qualityRun.output_artifacts?.report}>下载完整报告</Button>
              </Space>
              <div className="spot-weld-recipe__report-charts" aria-label="主要报告图表">
                {QUALITY_CHARTS.map(({ key, label }) => qualityRun.output_artifacts?.[key] && <figure key={key} className="spot-weld-recipe__report-chart">
                  <figcaption>{label}</figcaption>
                  {qualityChartUrls[key] ? <img src={qualityChartUrls[key]} alt={label} /> : <Spin size="small" />}
                </figure>)}
              </div>
            </Card>}
          </Space>
        </Card>}
      </section>}
    </AppLayout>
  );
}
