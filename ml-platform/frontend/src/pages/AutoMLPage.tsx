import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { App as AntApp, Card, Select, Button, Input, InputNumber, Typography, Table, Row, Col, Spin, Tag, Tabs, Modal, Form, Descriptions, Space, Switch } from "antd";
import { AimOutlined, AlertOutlined, CheckCircleFilled, ThunderboltOutlined, TrophyOutlined, BarChartOutlined, DownloadOutlined, EyeOutlined, PlusOutlined, ReloadOutlined, StopOutlined } from "@ant-design/icons";
import * as echarts from "echarts";
import apiClient, { formatApiError } from "../api/client";
import type { AutoMLRunPayload, AutoMLSearchMethod, AutoMLSearchStrength, AutoMLTaskType, AutoMLTimeBudget } from "../api/training";
import { getDatasetPreview, listDatasets } from "../api/datasets";
import {
  createQualityRun,
  downloadQualityArtifact,
  getQualityRun,
  type QualityAlgorithmId,
  type QualityRun,
} from "../api/spotWeldQuality";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import DeleteConfirmation from "../components/DeleteConfirmation";
import TableRowAction from "../components/TableRowAction";
import { useI18n } from "../i18n";
import { useAdaptivePolling } from "../hooks/useAdaptivePolling";
import { notifyDashboardStatsChanged } from "../events/dashboardStats";
import { taskStatusColor, taskStatusLabel } from "../utils/taskStatus";
import { formatLocalTime } from "../utils/time";
import { createUuid } from "../utils/uuid";

const { Text, Title } = Typography;

export const AUTOML_ALGORITHM_OPTIONS = [
  { value: "lightgbm", label: "LightGBM" },
  { value: "xgboost", label: "XGBoost" },
  { value: "catboost", label: "CatBoost" },
  { value: "gbdt", label: "GBDT" },
  { value: "random_forest", label: "Random Forest" },
  { value: "extra_trees", label: "Extra Trees" },
  { value: "hist_gradient_boosting", label: "HistGradientBoosting" },
  { value: "mlp", label: "MLP 神经网络" },
];
// 无监督（异常检测）族：仅 anomaly_detection 任务可选（范式互斥）。
// AE 第三族（二期 M5）：真实数据 comb 检出率 0.941 达标采纳（§6.1 门槛
// ocsvm 基线+0.05）；仅 high/ultra 搜索强度出场（引擎侧过滤，torch 缺失
// 时族自动缺席记 unavailable）。
export const AUTOML_ANOMALY_ALGORITHM_OPTIONS = [
  { value: "iforest", label: "IsolationForest 隔离森林" },
  { value: "ocsvm", label: "One-Class SVM 单类支持向量机" },
  { value: "autoencoder", label: "AutoEncoder 自编码器" },
];
export const AUTOML_ALGORITHM_IDS = AUTOML_ALGORITHM_OPTIONS.map(({ value }) => value);
export const AUTOML_ANOMALY_ALGORITHM_IDS = AUTOML_ANOMALY_ALGORITHM_OPTIONS.map(({ value }) => value);

// MLP 推荐默认（与拧紧质量感知报告一致）：adam / 0.001 / L2 1e-4 / 隐藏层 256-128-64。
const MLP_DEFAULT_PARAMS = {
  solver: "adam" as "adam" | "lbfgs" | "sgd",
  learning_rate_init: 0.001,
  alpha: 0.0001,
  hidden_layers: "256,128,64",
};
const MLP_HIDDEN_LAYER_OPTIONS = ["64", "128,64", "128,64,32", "256,128,64"];

const AUTOML_SEARCH_OPTIONS = [
  { value: "grid", label: "网格搜索" },
  { value: "random", label: "随机搜索" },
  { value: "bayesian", label: "贝叶斯优化" },
  { value: "evolutionary", label: "进化算法" },
  { value: "multi_fidelity", label: "多保真搜索" },
];

const AUTOML_TASK_OPTIONS = [
  { value: "classification", label: "Classification" },
  { value: "multioutput_classification", label: "Multi-output Classification" },
  { value: "regression", label: "Regression" },
  { value: "multioutput_regression", label: "Multi-output Regression" },
  { value: "anomaly_detection", label: "异常检测（无监督）" },
];

const AUTOML_STRENGTH_OPTIONS: Array<{ value: AutoMLSearchStrength; label: string }> = [
  { value: "light", label: "轻度（10 次）" },
  { value: "medium", label: "中（30 次）" },
  { value: "high", label: "高（80 次）" },
  { value: "ultra", label: "Ultra（200 次）" },
];
const AUTOML_TIME_BUDGET_OPTIONS: Array<{ value: AutoMLTimeBudget; label: string }> = [
  { value: 1800, label: "30 分钟" },
  { value: 3600, label: "60 分钟（标准）" },
  { value: 7200, label: "120 分钟" },
  { value: 14400, label: "240 分钟" },
];

function createRequestIdentifier(): string {
  return createUuid();
}

function formatAutoMLTimeBudget(value: unknown): string {
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return "-";
  return seconds % 60 === 0 ? `${seconds / 60} 分钟` : `${seconds} 秒`;
}

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
  project_name?: string;
  createdBy?: string;
  name?: string;
  experimentName?: string;
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
  const navigate = useNavigate();
  const { t, lang } = useI18n();
  const { message } = AntApp.useApp();
  const [projects, setProjects] = useState<any[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  // 实验自动创建（用户建议 1）：selectedExperiment 只存本次提交自动创建的实验 id
  const [selectedExperiment, setSelectedExperiment] = useState<string | null>(null);
  const [datasets, setDatasets] = useState<any[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);
  const [datasetColumns, setDatasetColumns] = useState<string[]>([]);
  const [numericInputColumns, setNumericInputColumns] = useState<string[]>([]);
  const [inputColumns, setInputColumns] = useState<string[]>([]);
  const [targetColumns, setTargetColumns] = useState<string[]>([]);
  const [taskType, setTaskType] = useState<AutoMLTaskType>("classification");
  // 无监督（异常检测）：预期异常比例先验，宁低勿高（缺省 1%，合法域 (0, 0.5]）
  const [contamination, setContamination] = useState<number>(0.01);
  const isAnomaly = taskType === "anomaly_detection";
  const [algorithmIds, setAlgorithmIds] = useState<string[]>(() => [...AUTOML_ALGORITHM_IDS]);
  const [mlpParams, setMlpParams] = useState<{ solver: "adam" | "lbfgs" | "sgd"; learning_rate_init: number; alpha: number; hidden_layers: string }>({ ...MLP_DEFAULT_PARAMS });
  // 默认关闭：全部 MLP 超参交给强度缩放后的自动搜索；开启后才按表单值固定
  const [mlpCustomizeEnabled, setMlpCustomizeEnabled] = useState(false);
  const [searchMethod, setSearchMethod] = useState<AutoMLSearchMethod>("bayesian");
  const [searchStrength, setSearchStrength] = useState<AutoMLSearchStrength>("medium");
  const [timeBudget, setTimeBudget] = useState<AutoMLTimeBudget>(3600);
  const [classWeight, setClassWeight] = useState(true);
  const [crossValidationEnabled, setCrossValidationEnabled] = useState(true);
  const [crossValidationFolds, setCrossValidationFolds] = useState<2 | 3 | 4 | 5>(5);
  // 终选层集成（多模型加权投票）：仅分类任务生效，引擎按主指标取前 K 名 soft-voting
  const [ensembleEnabled, setEnsembleEnabled] = useState(false);
  const [ensembleTopK, setEnsembleTopK] = useState<2 | 3 | 4 | 5>(3);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<any>(null);
  const [analysisReport, setAnalysisReport] = useState<Record<string, unknown> | null>(null);
  const [reportGenerating, setReportGenerating] = useState(false);
  const [activeTab, setActiveTab] = useState("results");
  const [recipeTab, setRecipeTab] = useState("general");
  const [qualityRunning, setQualityRunning] = useState(false);
  const [qualityAlgorithmIds, setQualityAlgorithmIds] = useState<QualityAlgorithmId[]>([]);
  const [qualityTargetColumn, setQualityTargetColumn] = useState("");
  const [qualityInputColumns, setQualityInputColumns] = useState<string[]>([]);
  const [qualityCrossValidationEnabled, setQualityCrossValidationEnabled] = useState(true);
  const [qualityCrossValidationFolds, setQualityCrossValidationFolds] = useState<3 | 4 | 5>(3);
  const [qualityRun, setQualityRun] = useState<QualityRun | null>(null);
  const [downloadingQualityReport, setDownloadingQualityReport] = useState(false);
  const [modelingTasks, setModelingTasks] = useState<ModelingTask[]>([]);
  const [loadingModelingTasks, setLoadingModelingTasks] = useState(false);
  const [viewingTaskKey, setViewingTaskKey] = useState<string | null>(null);
  const [stoppingTaskKey, setStoppingTaskKey] = useState<string | null>(null);
  const [qualityChartUrls, setQualityChartUrls] = useState<Record<string, string>>({});
  const [configurationOpen, setConfigurationOpen] = useState(false);
  // 范式入口卡片（用户建议 2 第二轮）：弹窗每次打开先选范式——有监督/无监督
  // 入口彻底分开，未选时不渲染具体表单（不再用混合的任务类型下拉）
  const [paradigmChosen, setParadigmChosen] = useState(false);
  const barRef = useRef<HTMLDivElement>(null);
  const radarRef = useRef<HTMLDivElement>(null);
  const resultRegionRef = useRef<HTMLDivElement>(null);
  const datasetPreviewRequestRef = useRef(0);
  const automlSubmissionRef = useRef<{ fingerprint: string; idempotencyKey: string } | null>(null);
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
    setLoadingModelingTasks(true);
    try {
      const ordinaryResponse = await apiClient.get("/training/automl/jobs", selectedProject ? { params: { project_id: selectedProject } } : undefined);
      const ordinaryItems = Array.isArray(ordinaryResponse.data)
        ? ordinaryResponse.data
        : ordinaryResponse.data?.items || [];
      const tasks: ModelingTask[] = [
        ...ordinaryItems
          .map((job: Record<string, unknown>) => ({
          id: String(job.id),
          project_id: String(job.project_id || selectedProject || ""),
          project_name: typeof job.project_name === "string" ? job.project_name : undefined,
          createdBy: typeof job.created_by_name === "string" ? job.created_by_name : typeof job.created_by_id === "string" ? job.created_by_id : undefined,
          name: String(job.name || "AutoML"),
          experimentName: typeof job.experiment_name === "string" ? job.experiment_name : undefined,
          status: String(job.status || "queued"),
          kind: "ordinary" as const,
          created_at: typeof job.created_at === "string" ? job.created_at : undefined,
          progress: (() => {
            const progress = normalizeProgress((job.metrics as Record<string, unknown> | undefined)?.progress || job.progress);
            return String(job.status) === "completed" ? { ...progress, percent: 100 } : progress;
          })(),
          errorCode: typeof job.error_code === "string" ? job.error_code : undefined,
          errorMessage: errorMessage(job.error_details) || (typeof job.error_message === "string" ? job.error_message : undefined),
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
    try {
      if (task.kind === "spot-weld") {
        const projectId = task.project_id || selectedProject;
        if (!projectId) {
          message.error("缺少任务项目，无法删除");
          return;
        }
        await apiClient.delete(`/projects/${projectId}/spot-weld/runs/${task.id}`);
      } else {
        await apiClient.delete(`/training/automl/jobs/${task.id}`);
      }
      notifyDashboardStatsChanged();
      message.success("建模任务已删除");
      await refreshModelingTasks();
    } catch (error) {
      message.error(formatApiError(error, "建模任务删除失败"));
    }
  };

  useEffect(() => {
    apiClient.get("/projects").then((res) => setProjects(res.data.items || res.data || [])).catch(() => {});
    void refreshModelingTasks();
  }, []);

  useEffect(() => {
    if (!selectedProject) {
      setDatasets([]); setSelectedDataset(null);
      setSelectedExperiment(null);
      return;
    }
    listDatasets(selectedProject).then(setDatasets).catch(() => setDatasets([]));
    // 实验自动创建（用户建议 1）：提交时按需创建专属实验，不再预取/预选
    setSelectedExperiment(null);
    void refreshModelingTasks();
  }, [selectedProject]);

  useAdaptivePolling(() => { void refreshModelingTasks(); }, {
    enabled: Boolean(selectedProject) && modelingTasks.some((task) => ["queued", "validating", "running", "pending"].includes(String(task.status))),
    intervalMs: 1500,
    signature: modelingTasks.map((task) => `${task.id}:${task.status}`).join(","),
  });

  useEffect(() => {
    const requestGeneration = ++datasetPreviewRequestRef.current;
    if (!selectedDataset) {
      setDatasetColumns([]);
      setNumericInputColumns([]);
      setInputColumns([]);
      setTargetColumns([]);
      setQualityInputColumns([]);
      setQualityTargetColumn("");
      return;
    }
    // Do not let a previous dataset schema authorize a run while the new preview is loading.
    setDatasetColumns([]);
    setNumericInputColumns([]);
    setInputColumns([]);
    setTargetColumns([]);
    setQualityInputColumns([]);
    setQualityTargetColumn("");
    getDatasetPreview(selectedDataset)
      .then((data) => {
        if (requestGeneration !== datasetPreviewRequestRef.current) return;
        const columns: string[] = Array.isArray(data.columns)
          ? data.columns.filter((column: unknown): column is string => typeof column === "string")
          : [];
        const dtypes = data.dtypes && typeof data.dtypes === "object" ? data.dtypes : {};
        setDatasetColumns(columns);
        setNumericInputColumns(columns.filter((column) => /^(?:u?int|float|complex)/i.test(String(dtypes[column] || ""))));
        setTargetColumns((current) => {
          const retained = current.filter((column) => columns.includes(column));
          if (retained.length) return retained;
          return columns.includes("label") ? ["label"] : [];
        });
        setQualityTargetColumn((current) => (
          columns.includes(current) && !QUALITY_REQUIRED_SOURCE_COLUMNS.includes(current) ? current : ""
        ));
      })
      .catch(() => {
        if (requestGeneration !== datasetPreviewRequestRef.current) return;
        setDatasetColumns([]); setNumericInputColumns([]); setInputColumns([]); message.error(t.common.error);
      });
  }, [selectedDataset, t.common.error, message]);

  useEffect(() => {
    const allowed = numericInputColumns.filter((column) => !targetColumns.includes(column));
    setInputColumns((current) => {
      const retained = current.filter((column) => allowed.includes(column));
      return retained.length ? retained : allowed;
    });
  }, [numericInputColumns, targetColumns]);

  useEffect(() => {
    setQualityInputColumns((current) => {
      return normalizeQualityInputColumns(current);
    });
  }, [datasetColumns, qualityTargetColumn]);

  const allResults = results?.models || results?.all_results || [];
  const bestModel = results?.best_model || allResults[0];
  const features = results?.feature_importance || results?.features || {};
  const handleTaskTypeChange = (task: AutoMLTaskType) => {
    setTaskType(task);
    if (task === "anomaly_detection") {
      // 范式互斥：无监督无目标列，切换即清空（换范式=重选任务）
      setTargetColumns([]);
      setAlgorithmIds(AUTOML_ANOMALY_ALGORITHM_IDS);
    } else {
      if (!task.startsWith("multioutput") && targetColumns.length > 1) {
        setTargetColumns(targetColumns.slice(0, 1));
      }
      setAlgorithmIds((ids) => ids.filter((id) => !AUTOML_ANOMALY_ALGORITHM_IDS.includes(id as never)));
    }
    setClassWeight(task.includes("classification"));
  };

  const handleSearchStrengthChange = (strength: AutoMLSearchStrength) => {
    setSearchStrength(strength);
  };

  const viewModelingTask = async (task: ModelingTask) => {
    navigate(`/automl/task/${task.id}`);
  };

  const stopModelingTask = async (task: ModelingTask) => {
    if (task.kind !== "ordinary" || !["pending", "queued", "running"].includes(String(task.status))) return;
    setStoppingTaskKey(`${task.kind}-${task.id}`);
    try {
      await apiClient.post(`/training/jobs/${task.id}/stop`);
      notifyDashboardStatsChanged();
      message.success("已提交停止任务请求");
      await refreshModelingTasks();
    } catch (error) {
      message.error(formatApiError(error, "任务停止失败"));
    } finally {
      setStoppingTaskKey(null);
    }
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
    const isMultiOutput = taskType.startsWith("multioutput");
    if (!selectedProject || !selectedDataset || inputColumns.length === 0 || (!isAnomaly && !targetColumns.length) || (isMultiOutput && targetColumns.length < 2)) {
      message.warning((t.automl?.select_project || "Project") + " / " + (t.automl?.select_dataset || "Dataset") + " / " + (t.automl?.target || "Target"));
      return;
    }
    if (isAnomaly && (!(contamination > 0) || contamination > 0.5)) {
      message.warning("污染率（预期异常比例）必须在 (0, 0.5] 区间内，建议宁低勿高");
      return;
    }
    setRunning(true);
    setResults(null);
    setAnalysisReport(null);
    try {
      // 实验自动创建（用户建议 1）：后端约束一实验只能绑一个 AutoML 任务，
      // 下拉选择注定撞 409——每次提交自动创建专属实验（秒级时间戳保证唯一）。
      let experimentId: string = selectedExperiment ?? "";
      if (!experimentId) {
        const now = new Date();
        const pad = (n: number) => String(n).padStart(2, "0");
        const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
        const created = await apiClient.post("/experiments", {
          project_id: selectedProject,
          name: `自动建模-${stamp}`,
          description: "",
        });
        experimentId = String(created.data.id);
        setSelectedExperiment(experimentId);
      }
      const payloadBase = {
        project_id: selectedProject, experiment_id: experimentId,
        dataset_artifact_id: selectedDataset,
        input_columns: inputColumns,
        algorithm_ids: algorithmIds,
        // 仅当用户显式开启「自定义 MLP 超参」时才固定；默认关闭=全部参数
        // 交给强度缩放后的自动搜索（否则默认值会钉死隐藏层/学习率/正则化，
        // 搜索强度只剩 max_iter 可变）。
        ...(algorithmIds.includes("mlp") && mlpCustomizeEnabled ? { algorithm_params: { mlp: mlpParams } } : {}),
        // 无监督不支持多保真（Hyperband int 资源 rung 与 OC-SVM 不匹配），降级随机搜索
        search_method: isAnomaly && searchMethod === "multi_fidelity" ? "random" : searchMethod,
        time_budget: timeBudget,
        search_strength: searchStrength,
        class_weight: classWeight,
        cross_validation_enabled: crossValidationEnabled,
        cross_validation_folds: crossValidationEnabled ? crossValidationFolds : null,
      };
      const payload: AutoMLRunPayload = isAnomaly
        ? {
            ...payloadBase,
            task: "anomaly_detection",
            // 无监督：无目标列（镜像互斥）；引擎用合成异常基准替代常规 CV
            cross_validation_enabled: false,
            cross_validation_folds: null,
            ...(contamination > 0 && contamination <= 0.5 ? { contamination } : {}),
          }
        : isMultiOutput
        ? {
            ...payloadBase,
            task: taskType as "multioutput_classification" | "multioutput_regression",
            target_columns: targetColumns as [string, string, ...string[]],
          }
        : {
            ...payloadBase,
            task: taskType as "classification" | "regression",
            target_column: targetColumns[0],
            // 集成仅单输出分类生效（引擎回归/多输出不支持 soft-voting）
            ...(ensembleEnabled && taskType === "classification"
              ? { ensemble: { enabled: true, top_k: ensembleTopK } }
              : {}),
          };
      const fingerprint = JSON.stringify(payload);
      const existingSubmission = automlSubmissionRef.current;
      const submission = existingSubmission && existingSubmission.fingerprint === fingerprint
        ? existingSubmission
        : { fingerprint, idempotencyKey: createRequestIdentifier() };
      automlSubmissionRef.current = submission;
      const res = await apiClient.post("/training/automl/run", payload, {
        headers: {
          "Idempotency-Key": submission.idempotencyKey,
          "X-Request-ID": createRequestIdentifier(),
        },
      });
      automlSubmissionRef.current = null;
      notifyDashboardStatsChanged();
      void refreshModelingTasks();
      const rid = res.data.run_id || res.data.id || res.data.job_id;
      setRunning(false);
      setConfigurationOpen(false);
      navigate(`/automl/task/${rid}`);
    } catch (e: any) {
      message.error(formatApiError(e, t.common.error));
      setRunning(false);
    }
  };

  const generateAnalysisReport = () => {
    if (!results) return;
    setReportGenerating(true);
    const models = Array.isArray(results.models || results.all_results) ? (results.models || results.all_results) : [];
    const best = results.best_model || models[0] || null;
    setAnalysisReport({
      title: "通用自动建模分析报告",
      generated_at: new Date().toISOString(),
      project_id: selectedProject,
      experiment_id: selectedExperiment,
      dataset_id: selectedDataset,
      task: taskType,
      search_method: searchMethod,
      best_model: best,
      models,
      feature_importance: results.feature_importance || results.features || {},
      metrics: results.metrics || {},
    });
    setReportGenerating(false);
    message.success("分析报告已生成");
  };

  const exportAnalysisReport = () => {
    if (!analysisReport) return;
    const blob = new Blob([JSON.stringify(analysisReport, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `automl-analysis-report-${selectedProject || "report"}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    message.success("分析报告已导出");
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
        algorithm_ids: qualityAlgorithmIds,
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

  useAdaptivePolling(async () => {
    if (!selectedProject || !qualityRun) return;
    try {
      const latest = await getQualityRun(selectedProject, qualityRun.id);
      setQualityRun(latest);
      void refreshModelingTasks();
    } catch {
      // Annotation workspace remains the recovery path when a queued task is no longer readable.
    }
  }, {
    enabled: Boolean(selectedProject && qualityRun && ["queued", "validating", "running"].includes(String(qualityRun.status))),
    intervalMs: 1500,
    signature: String(qualityRun?.status ?? ""),
    immediate: true,
  });

  useEffect(() => {
    let active = true;
    const artifacts = qualityRun?.output_artifacts || {};
    if (!selectedProject || qualityRun?.status !== "completed") {
      // A 批次十四：替换/清空前回收既有 blob URL
      setQualityChartUrls((current) => {
        for (const url of Object.values(current)) URL.revokeObjectURL(url);
        return {};
      });
      return () => { active = false; };
    }
    const available = QUALITY_CHARTS.filter(({ key }) => artifacts[key]);
    if (available.length === 0) {
      setQualityChartUrls((current) => {
        for (const url of Object.values(current)) URL.revokeObjectURL(url);
        return {};
      });
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
      if (!active) {
        // A 批次十四：组件卸载/切换 run 后回收未消费的 blob URL
        for (const [, url] of entries) {
          if (url) URL.revokeObjectURL(url);
        }
        return;
      }
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
    { title: "Task", dataIndex: "task_type", key: "task", render: (value: string) => value === "anomaly_detection" ? "异常检测（无监督）" : value },
    {
      title: "Time",
      key: "time",
      render: (_value: unknown, row: { training_time_seconds?: number | null; training_time?: number | null }) => {
        const value = row.training_time_seconds ?? row.training_time;
        return value != null ? `${Number(value).toFixed(1)}s` : "-";
      },
    },
  ];
  const algorithmResults = Array.isArray(results?.algorithm_results) ? results.algorithm_results : [];
  const formatParams = (value: unknown) => value && typeof value === "object"
    ? Object.entries(value as Record<string, unknown>).sort(([left], [right]) => left.localeCompare(right)).map(([key, item]) => `${key}=${String(item)}`).join(", ")
    : "-";
  const algorithmResultColumns = [
    { title: "算法", dataIndex: "name", key: "name", render: (value: string, row: any) => value || row.algorithm_id },
    { title: "状态", dataIndex: "status", key: "status", render: (value: string) => <Tag color={value === "completed" ? "green" : value === "unavailable" ? "orange" : "red"}>{value}</Tag> },
    { title: "最佳分数", dataIndex: "best_score", key: "score", render: (value: number | null) => value == null ? "-" : Number(value).toFixed(4) },
    { title: "最佳参数", dataIndex: "best_params", key: "params", render: (value: unknown) => <Text title={formatParams(value)}>{formatParams(value)}</Text> },
    { title: "完成/剪枝/失败", key: "trials", render: (_value: unknown, row: any) => `${row.completed_trials || 0}/${row.pruned_trials || 0}/${row.failed_trials || 0}` },
  ];

  const featureEntries = Object.entries(features).sort((a: any, b: any) => b[1] - a[1]);
  const maxImp = featureEntries.length > 0 ? (featureEntries[0][1] as number) : 1;
  const qualityCandidates = Array.isArray(qualityRun?.automl_results) ? qualityRun.automl_results : [];
  const qualityCluster = qualityRun?.clustering_results || {};
  const qualityKSearch = Object.entries((qualityCluster.silhouette_scores || {}) as Record<string, number>);
  const qualityPca = Array.isArray(qualityCluster.pca_coordinates) ? qualityCluster.pca_coordinates : [];
  const qualityBestCandidate = qualityCandidates.find((candidate) => candidate.error_code == null) || qualityCandidates[0];
  const formatQualityMetric = (key: "auc" | "f1") => {
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
    { title: "项目", dataIndex: "project_name", key: "project", render: (value: string | undefined, row: ModelingTask) => value || row.project_id || "-" },
    { title: "创建人", dataIndex: "createdBy", key: "creator", render: (value: string | undefined) => value || "-" },
    { title: "实验", dataIndex: "experimentName", key: "experiment", render: (value: string | undefined, row: ModelingTask) => <Space size={6}><strong>{value || "-"}</strong><Tag color={row.kind === "spot-weld" ? "blue" : "default"}>{row.kind === "spot-weld" ? "点焊建模" : "自动建模"}</Tag></Space> },
    { title: "状态", dataIndex: "status", key: "status", render: (value: string) => <Tag color={taskStatusColor(value)}>{taskStatusLabel(value, lang)}</Tag> },
    { title: "建模进度", key: "progress", render: (_value: unknown, row: ModelingTask) => `${row.progress.completed}/${row.progress.total} ${row.progress.percent}%` },
    { title: "错误详情", key: "error", render: (_value: unknown, row: ModelingTask) => (row.errorCode || row.errorMessage) ? <Space direction="vertical" size={0}><Text type="danger">{row.errorCode}</Text>{row.errorMessage && <Text type="danger">{row.errorMessage}</Text>}</Space> : "-" },
    { title: "操作", key: "actions", align: "right" as const, render: (_value: unknown, row: ModelingTask) => <div className="table-row-actions">
      <TableRowAction label={`查看建模结果 ${row.id}`} icon={<EyeOutlined />} loading={viewingTaskKey === `${row.kind}-${row.id}`} onClick={() => void viewModelingTask(row)} />
      {row.kind === "ordinary" && ["pending", "queued", "running"].includes(String(row.status)) && <TableRowAction label={`停止建模任务 ${row.id}`} icon={<StopOutlined />} warning loading={stoppingTaskKey === `${row.kind}-${row.id}`} onClick={() => void stopModelingTask(row)} />}
      <DeleteConfirmation label={`删除建模任务 ${row.id}`} targetName={row.experimentName || row.id} onConfirm={() => void deleteModelingTask(row)} disabled={!['completed', 'failed', 'cancelled', 'cancel_requested'].includes(String(row.status))} />
    </div> },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="algo" navKey="automl" testId="v2-automl">
      <Card title="建模任务" style={{ marginBottom: 16 }} extra={(
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void refreshModelingTasks()} loading={loadingModelingTasks}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} aria-label="新建" onClick={() => { setRecipeTab("general"); setResults(null); setParadigmChosen(false); setConfigurationOpen(true); }}>新建</Button>
        </Space>
      )}>
        <div className="table-surface"><Table<ModelingTask> rowKey={(task) => `${task.kind}-${task.id}`} size="small" columns={modelingTaskColumns} dataSource={modelingTasks} loading={loadingModelingTasks} pagination={false} locale={{ emptyText: "暂无建模任务" }} /></div>
      </Card>
      {configurationOpen && <Modal title={taskType === "anomaly_detection" ? "新建无监督异常检测" : (paradigmChosen ? "新建有监督建模" : "新建自动建模")} open={configurationOpen} onCancel={() => setConfigurationOpen(false)} footer={null} width={1100} destroyOnClose>
      {/* 范式入口卡片（用户建议 2）：有监督/无监督入口彻底分开——每次新建
          先点范式卡片，未选时不出具体表单；不再共用「任务类型」下拉。
          视觉：图标底块 + 选中主色描边/浅底 + 勾选角标 + hover 上浮（深浅
          主题经 CSS 变量与半透明选色自适应） */}
      <style>{`
        .paradigm-card { transition: all .2s ease; }
        .paradigm-card:hover { transform: translateY(-2px); box-shadow: 0 4px 14px rgba(24,144,255,0.18); border-color: #69b1ff !important; }
        .paradigm-card:hover .paradigm-card-icon { background: #1890ff; color: #fff; }
      `}</style>
      {/* flex+gap 布局：antd Row 的 gutter 负 margin 会让卡片溢出 Modal
          padding 边界（外层 Card 壳移除后暴露），gap 正间距无此问题 */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: paradigmChosen ? 16 : 8 }}>
          <div style={{ flex: "1 1 380px", display: "flex" }}>
            <div role="button" aria-label="范式：有监督建模" tabIndex={0}
              onClick={() => { setParadigmChosen(true); handleTaskTypeChange("classification"); }}
              onKeyDown={(e) => { if (e.key === "Enter") { setParadigmChosen(true); handleTaskTypeChange("classification"); } }}
              className="paradigm-card"
              style={{ cursor: "pointer", position: "relative", flex: 1, borderRadius: 10,
                border: `2px solid ${paradigmChosen && taskType !== "anomaly_detection" ? "#1890ff" : "var(--v2-line, #e5e5e5)"}`,
                background: paradigmChosen && taskType !== "anomaly_detection" ? "rgba(24,144,255,0.08)" : "var(--v2-panel, #fff)",
                padding: "14px 16px 12px 60px" }}>
              <span className="paradigm-card-icon" style={{ position: "absolute", left: 16, top: 16, width: 30, height: 30, borderRadius: 8,
                background: paradigmChosen && taskType !== "anomaly_detection" ? "#1890ff" : "rgba(24,144,255,0.12)",
                color: paradigmChosen && taskType !== "anomaly_detection" ? "#fff" : "#1890ff",
                display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, transition: "all .2s ease" }}>
                <AimOutlined />
              </span>
              <Text strong style={{ fontSize: 14 }}>有监督建模</Text>
              {paradigmChosen && taskType !== "anomaly_detection" && (
                <CheckCircleFilled style={{ position: "absolute", right: 12, top: 16, color: "#1890ff", fontSize: 16 }} />
              )}
              <div style={{ fontSize: 12, color: "var(--text-secondary, rgba(0,0,0,0.45))", marginTop: 6, lineHeight: 1.7 }}>
                有标签数据，学习特征到标签的映射<br />
                <span style={{ fontSize: 11.5 }}>Classification / Regression / 多输出 · 集成学习 · 交叉验证</span>
              </div>
            </div>
          </div>
          <div style={{ flex: "1 1 380px", display: "flex" }}>
            <div role="button" aria-label="范式：无监督异常检测" tabIndex={0}
              onClick={() => { setParadigmChosen(true); handleTaskTypeChange("anomaly_detection"); }}
              onKeyDown={(e) => { if (e.key === "Enter") { setParadigmChosen(true); handleTaskTypeChange("anomaly_detection"); } }}
              className="paradigm-card"
              style={{ cursor: "pointer", position: "relative", flex: 1, borderRadius: 10,
                border: `2px solid ${taskType === "anomaly_detection" ? "#1890ff" : "var(--v2-line, #e5e5e5)"}`,
                background: taskType === "anomaly_detection" ? "rgba(24,144,255,0.08)" : "var(--v2-panel, #fff)",
                padding: "14px 16px 12px 60px" }}>
              <span className="paradigm-card-icon" style={{ position: "absolute", left: 16, top: 16, width: 30, height: 30, borderRadius: 8,
                background: taskType === "anomaly_detection" ? "#1890ff" : "rgba(255,122,69,0.12)",
                color: taskType === "anomaly_detection" ? "#fff" : "#fa8c16",
                display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, transition: "all .2s ease" }}>
                <AlertOutlined />
              </span>
              <Text strong style={{ fontSize: 14 }}>无监督异常检测</Text>
              {taskType === "anomaly_detection" && (
                <CheckCircleFilled style={{ position: "absolute", right: 12, top: 16, color: "#1890ff", fontSize: 16 }} />
              )}
              <div style={{ fontSize: 12, color: "var(--text-secondary, rgba(0,0,0,0.45))", marginTop: 6, lineHeight: 1.7 }}>
                只用正常数据，检测多维联合分布异常<br />
                <span style={{ fontSize: 11.5 }}>污染率先验 · IsolationForest / One-Class SVM · 漂移治理</span>
              </div>
            </div>
      </div>
      </div>
      {paradigmChosen && <>
        <Row gutter={[16, 16]} align="middle" style={{ marginBottom: 4 }}>
          <Col xs={24} sm={6}><Text strong>{t.automl?.select_project || "Project"}</Text>
            <Select style={{ width: "100%", marginTop: 4 }} placeholder={t.automl?.select_project} value={selectedProject} onChange={setSelectedProject}
              options={projects.map((p: any) => ({ value: p.id, label: p.name }))} /></Col>
          <Col xs={24} sm={6}><Text strong>{t.automl?.select_dataset || "Dataset"}</Text>
            <Select style={{ width: "100%", marginTop: 4 }} placeholder={t.automl?.select_dataset} value={selectedDataset} onChange={setSelectedDataset}
              options={datasets.map((d: any) => ({ value: d.id, label: d.name || d.filename }))} /></Col>
          {/* 实验自动创建（用户建议 1）：一实验一任务的后端约束下，下拉选择
              注定撞 409——提交时自动创建专属实验，不再展示实验选择 */}
          <Col xs={24} sm={4}>{taskType === "anomaly_detection" ? (<>
            <Text strong>污染率（预期异常比例）</Text>
            <InputNumber aria-label="污染率" style={{ width: "100%", marginTop: 4 }}
              min={0.001} max={0.5} step={0.005} value={contamination}
              onChange={(value) => setContamination(Number(value) || 0.01)} />
            <small style={{ display: "block", color: "rgba(0,0,0,0.45)" }}>宁低勿高，缺省 1%</small>
          </>) : (<>
            <Text strong>{t.automl?.target || "Target"}</Text>
            <Select
              aria-label="目标列"
              mode={taskType.startsWith("multioutput") ? "multiple" : undefined}
              maxTagCount="responsive"
              style={{ width: "100%", marginTop: 4 }}
              placeholder={t.automl?.target}
              value={taskType.startsWith("multioutput") ? targetColumns : targetColumns[0] || undefined}
              onChange={(columns: string[] | string) => setTargetColumns(Array.isArray(columns) ? columns : columns ? [columns] : [])}
              disabled={!selectedDataset}
              options={datasetColumns.map((column) => ({ value: column, label: column }))}
            /></>)}</Col>
          <Col xs={24} sm={6}><Text strong>输入列</Text>
            <Select
              aria-label="输入列"
              mode="multiple"
              allowClear
              maxTagCount="responsive"
              style={{ width: "100%", marginTop: 4 }}
              placeholder="选择数值输入列"
              value={inputColumns}
              onChange={(columns: string[]) => setInputColumns(columns.filter((column) => !targetColumns.includes(column)))}
              disabled={!selectedDataset}
              options={numericInputColumns.filter((column) => !targetColumns.includes(column)).map((column) => ({ value: column, label: column }))}
            /></Col>
          {isAnomaly ? null : (
          <Col xs={24} sm={4}><Text strong>任务子类型</Text>
            <Select aria-label="任务子类型" style={{ width: "100%", marginTop: 4 }} value={taskType} onChange={handleTaskTypeChange}
              options={AUTOML_TASK_OPTIONS.filter((option) => option.value !== "anomaly_detection")} /></Col>
          )}
          <Col xs={24} sm={6}><Text strong>算法家族</Text>
            <Select
              aria-label="算法家族"
              mode="multiple"
              allowClear
              maxTagCount="responsive"
              style={{ width: "100%", marginTop: 4 }}
              placeholder="默认全部算法"
              value={algorithmIds}
              onChange={setAlgorithmIds}
              options={taskType === "anomaly_detection" ? AUTOML_ANOMALY_ALGORITHM_OPTIONS : AUTOML_ALGORITHM_OPTIONS}
            /></Col>
          {algorithmIds.includes("mlp") && <>
            <Col xs={12} sm={4}><Text strong>自定义 MLP 超参</Text>
              <div style={{ marginTop: 7 }}><Switch
                aria-label="自定义 MLP 超参"
                checked={mlpCustomizeEnabled}
                onChange={setMlpCustomizeEnabled}
              /></div>
              <small style={{ display: "block", color: "rgba(0,0,0,0.45)" }}>
                {mlpCustomizeEnabled ? "按下方固定值训练" : "关闭=随搜索强度自动调参"}
              </small>
            </Col>
            <Col xs={12} sm={4}><Text strong>MLP 优化器</Text>
              <Select aria-label="MLP 优化器" style={{ width: "100%", marginTop: 4 }} value={mlpParams.solver} disabled={!mlpCustomizeEnabled}
                onChange={(solver: "adam" | "lbfgs" | "sgd") => setMlpParams((current) => ({ ...current, solver }))}
                options={[
                  { value: "adam", label: "Adam（推荐）" },
                  { value: "lbfgs", label: "L-BFGS（小数据集）" },
                  { value: "sgd", label: "SGD" },
                ]} /></Col>
            <Col xs={12} sm={4}><Text strong>MLP 学习率</Text>
              <InputNumber aria-label="MLP 学习率" style={{ width: "100%", marginTop: 4 }} min={0.0001} max={0.1} step={0.0005}
                value={mlpParams.learning_rate_init} disabled={!mlpCustomizeEnabled}
                onChange={(value) => setMlpParams((current) => ({ ...current, learning_rate_init: Number(value) || MLP_DEFAULT_PARAMS.learning_rate_init }))} /></Col>
            <Col xs={12} sm={4}><Text strong>MLP 正则化 (L2 α)</Text>
              <InputNumber aria-label="MLP 正则化" style={{ width: "100%", marginTop: 4 }} min={0.000001} max={0.1} step={0.0001}
                value={mlpParams.alpha} disabled={!mlpCustomizeEnabled}
                onChange={(value) => setMlpParams((current) => ({ ...current, alpha: Number(value) || MLP_DEFAULT_PARAMS.alpha }))} /></Col>
            <Col xs={12} sm={6}><Text strong>MLP 隐藏层</Text>
              <Select aria-label="MLP 隐藏层" style={{ width: "100%", marginTop: 4 }} value={mlpParams.hidden_layers} disabled={!mlpCustomizeEnabled}
                onChange={(hidden_layers: string) => setMlpParams((current) => ({ ...current, hidden_layers }))}
                options={MLP_HIDDEN_LAYER_OPTIONS.map((layers) => ({ value: layers, label: layers }))} /></Col>
          </>}
          <Col xs={24} sm={4}><Text strong>搜索方法</Text>
            <Select aria-label="搜索方法" style={{ width: "100%", marginTop: 4 }} value={searchMethod} onChange={setSearchMethod}
              options={AUTOML_SEARCH_OPTIONS.map((option) => option.value === "multi_fidelity" && taskType === "anomaly_detection"
                ? { ...option, label: "多保真搜索（无监督不可用）", disabled: true }
                : option)} /></Col>
          <Col xs={12} sm={3}><Text strong>搜索强度</Text>
            <Select aria-label="搜索强度" style={{ width: "100%", marginTop: 4 }} value={searchStrength} onChange={handleSearchStrengthChange}
              options={AUTOML_STRENGTH_OPTIONS} /></Col>
          <Col xs={12} sm={3}><Text strong>总时间上限</Text>
            <Select aria-label="总时间上限" style={{ width: "100%", marginTop: 4 }} value={timeBudget} onChange={setTimeBudget}
              options={AUTOML_TIME_BUDGET_OPTIONS} /></Col>
          {/* 范式分组（用户建议 2）：类别权重/交叉验证/集成学习是监督专属——
              无监督只保留搜索控制与污染率，payload 层本就忽略这些值 */}
          {!isAnomaly && (
          <Col xs={12} sm={3}><Text strong>类别权重</Text>
            <div style={{ marginTop: 7 }}><Switch aria-label="类别权重" checked={classWeight} disabled={!taskType.includes("classification")} onChange={setClassWeight} /></div></Col>
          )}
          {!isAnomaly && (
          <Col xs={12} sm={3}><Text strong>交叉验证</Text>
            <div style={{ marginTop: 7 }}><Switch aria-label="启用交叉验证" checked={crossValidationEnabled} onChange={setCrossValidationEnabled} /></div></Col>
          )}
          {!isAnomaly && (
          <Col xs={12} sm={3}><Text strong>折数</Text>
            <Select
              aria-label="交叉验证折数"
              style={{ width: "100%", marginTop: 4 }}
              value={crossValidationFolds}
              disabled={!crossValidationEnabled}
              onChange={(folds: 2 | 3 | 4 | 5) => setCrossValidationFolds(folds)}
              options={[2, 3, 4, 5].map((folds) => ({ value: folds, label: `${folds} 折` }))}
            /></Col>
          )}
          {!isAnomaly && (
          <Col xs={12} sm={3}><Text strong>集成学习</Text>
            <div style={{ marginTop: 7 }}><Switch aria-label="启用集成学习" checked={ensembleEnabled}
              disabled={taskType !== "classification"} onChange={setEnsembleEnabled} /></div></Col>
          )}
          {!isAnomaly && (
          <Col xs={12} sm={3}><Text strong>集成成员</Text>
            <Select
              aria-label="集成成员数"
              style={{ width: "100%", marginTop: 4 }}
              value={ensembleTopK}
              disabled={!ensembleEnabled || taskType !== "classification"}
              onChange={(k: 2 | 3 | 4 | 5) => setEnsembleTopK(k)}
              options={[2, 3, 4, 5].map((k) => ({ value: k, label: `前 ${k} 名` }))}
            /></Col>
          )}
          <Col xs={24} sm={2}><Button type="primary" icon={<ThunderboltOutlined />} onClick={handleRun} loading={running} block style={{ marginTop: 22 }}>{t.automl?.run || "Run"}</Button></Col>
        </Row>
      </>}

      {paradigmChosen && running && <Card style={{ textAlign: "center", padding: 40 }}><Spin size="large" /><p style={{ marginTop: 16 }}>{t.common.loading}</p></Card>}

      {results && (
        <div ref={resultRegionRef}>
        {results.search && <section style={{ marginBottom: 16 }}>
          <Space wrap size="large" style={{ marginBottom: 10 }}>
            <Text strong>{`搜索方法：${results.search.method}`}</Text>
            <Text>{`最大试验：${results.search.max_trials}`}</Text>
            <Text>{`时间上限：${formatAutoMLTimeBudget(results.search.time_budget)}`}</Text>
            {results.search.budget_exhausted && <Tag color="orange">预算已耗尽</Tag>}
          </Space>
          {bestModel?.params && <div style={{ marginBottom: 10 }}><Text strong>最佳参数：</Text><Text>{formatParams(bestModel.params)}</Text></div>}
          <Table rowKey={(row: any) => row.algorithm_id} dataSource={algorithmResults} columns={algorithmResultColumns} size="small" pagination={false} scroll={{ x: 760 }} />
        </section>}
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          { key: "results", label: "Results",
            children: (<>
              {bestModel && (
                <Card style={{ marginBottom: 16 }}>
                  <Space style={{ marginBottom: 12 }}>
                    <Button type="primary" onClick={generateAnalysisReport} loading={reportGenerating}>生成分析报告</Button>
                    <Button icon={<DownloadOutlined />} onClick={exportAnalysisReport} disabled={!analysisReport}>导出报告</Button>
                  </Space>
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
                  {analysisReport && <Text type="secondary">报告已生成：{formatLocalTime(String(analysisReport.generated_at), true)}</Text>}
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
        </div>
      )}
      </Modal>}
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
              <Text strong>质量感知算法家族</Text>
              <Select
                mode="multiple"
                aria-label="质量感知算法家族"
                style={{ width: "100%", marginTop: 4 }}
                value={qualityAlgorithmIds}
                onChange={(values: QualityAlgorithmId[]) => setQualityAlgorithmIds(values)}
                placeholder="留空使用全部算法家族"
                options={AUTOML_ALGORITHM_OPTIONS}
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
      </V2PageFrame>
    </AppLayout>
  );
}
