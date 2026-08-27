import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { App as AntApp, Dropdown, Empty, Spin, Steps, Table, Tag, Tooltip } from "antd";
import { DeleteOutlined, DownloadOutlined, EyeOutlined, LeftOutlined, ReloadOutlined, RightOutlined, UploadOutlined } from "@ant-design/icons";
import { useNavigate, useSearchParams } from "react-router-dom";
import * as echarts from "echarts";

import AppLayout from "../components/AppLayout";
import DeleteConfirmation from "../components/DeleteConfirmation";
import TableRowAction from "../components/TableRowAction";
import { useI18n } from "../i18n";
import { taskStatusColor, taskStatusLabel } from "../utils/taskStatus";
import { formatApiError, default as apiClient } from "../api/client";
import { listDatasets } from "../api/datasets";
import {
  createQualityRun,
  deleteQualityRun,
  downloadQualityAnnotationExport,
  getQualitySample,
  getQualityRun,
  listQualityRuns,
  listQualitySamples,
  listQualityDatasetColumns,
  listQualityModels,
  previewQualityClusters,
  saveLabeledDataset,
  submitQualityLabel,
  type QualityRun,
  type QualityLabelMode,
  type QualityModel,
  type QualitySample,
  type QualitySampleDetail,
  type AnnotationProcessRule,
  type AnnotationRuleTokenKind,
  uploadQualityDataset,
  validateQualityDataset,
} from "../api/spotWeldQuality";
import type { QualityClusterPreview } from "../api/spotWeldQuality";

interface ProjectOption { id: string; name: string; project_role?: string; }

interface DatasetOption {
  id?: string;
  artifact_id?: string;
  name?: string;
  format?: string;
  row_count?: number;
}

type LabelOption = readonly [string, string];
type CreatedTargetColumnDtype = "int" | "float" | "string";
interface AnnotationRuleToken { kind: AnnotationRuleTokenKind; value: string; }
type AnnotationRule = Omit<AnnotationProcessRule, "tokens"> & { tokens: AnnotationRuleToken[] };

const CLUSTER_COLORS = ["#1677ff", "#d4380d", "#389e0d", "#d48806", "#722ed1", "#08979c", "#c41d7f", "#531dab"];

function clusterColor(clusterId: number): string {
  return CLUSTER_COLORS[Math.abs(clusterId) % CLUSTER_COLORS.length];
}

const CREATED_TARGET_COLUMN_DTYPE_OPTIONS: ReadonlyArray<readonly [CreatedTargetColumnDtype, string]> = [
  ["int", "整数（int）"],
  ["float", "浮点数（float）"],
  ["string", "文本（string）"],
];

function qualityLabelText(value: string | null | undefined): string {
  if (!value) return "-";
  return value;
}

function labelOptionsForRun(run: QualityRun | undefined): LabelOption[] {
  const classes = run?.target_schema?.classes || [];
  return classes.map((value) => [value, value] as const);
}

function labelHeadingForRun(run: QualityRun | undefined, copy: { humanLabel: string }): string {
  if (run?.label_mode !== "manual" || !run.target_schema?.name || !run.target_schema?.dtype) return copy.humanLabel;
  return `${copy.humanLabel}（${run.target_schema.name} · ${run.target_schema.dtype}）`;
}

function normalizeLabelValue(value: string, run: QualityRun | undefined): string | null {
  const raw = value.trim();
  if (!raw) return null;
  const dtype = String(run?.target_schema?.dtype || "").toLowerCase();
  if (dtype.startsWith("int") || dtype === "integer" || dtype === "int") {
    const number = Number(raw);
    return Number.isFinite(number) && Number.isInteger(number) ? String(number) : null;
  }
  if (dtype.startsWith("float") || dtype === "double" || dtype === "number") {
    const number = Number(raw);
    return Number.isFinite(number) ? String(number) : null;
  }
  return raw;
}

function annotationProgressText(run: QualityRun): string {
  const progress = run.annotation_progress;
  if (!progress) return "0/0 0%";
  return `${progress.annotated_count}/${progress.total_count} ${progress.percent}%`;
}

function runModeText(run: QualityRun, copy: { manual: string; automatic: string }): string {
  return run.label_mode === "manual" ? copy.manual : copy.automatic;
}

function normalizeLabelDtype(value: string | null | undefined): CreatedTargetColumnDtype {
  const normalized = String(value || "").toLowerCase();
  if (normalized.includes("float") || normalized === "double" || normalized === "number") return "float";
  if (normalized.includes("int") || normalized === "integer") return "int";
  return "string";
}

function runStatusText(run: QualityRun, lang: "zh" | "en"): string {
  return taskStatusLabel(run.status, lang);
}

const warningColor: Record<string, string> = {
  critical: "red", warning: "orange", notice: "gold", none: "green",
};

function fullSampleValue(value: unknown): string {
  const displayValue = value;
  if (typeof displayValue === "string") return displayValue;
  if (displayValue == null) return "-";
  if (Array.isArray(displayValue)) return `[${displayValue.map((item) => String(item)).join(", ")}]`;
  if (typeof displayValue === "object") return JSON.stringify(displayValue);
  return String(displayValue);
}

export default function DataAnnotationPage() {
  const { message } = AntApp.useApp();
  const { lang, t } = useI18n();
  const copy = t.dataAnnotation;
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState(searchParams.get("projectId") || "");
  const [datasetArtifactId, setDatasetArtifactId] = useState(searchParams.get("datasetId") || "");
  const [runs, setRuns] = useState<QualityRun[]>([]);
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [runId, setRunId] = useState(searchParams.get("runId") || "");
  const [samples, setSamples] = useState<QualitySample[]>([]);
  const [selected, setSelected] = useState<QualitySampleDetail | null>(null);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [loadingDatasets, setLoadingDatasets] = useState(false);
  const [loadingSamples, setLoadingSamples] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [downloadingAnnotationExport, setDownloadingAnnotationExport] = useState(false);
  const [savingLabeledDataset, setSavingLabeledDataset] = useState(false);
  const [label, setLabel] = useState("");
  const [labelOptions, setLabelOptions] = useState<LabelOption[]>([]);
  const [editingLabelList, setEditingLabelList] = useState(false);
  const [newLabelText, setNewLabelText] = useState("");
  const [savingLabel, setSavingLabel] = useState(false);
  const [preparingRun, setPreparingRun] = useState(false);
  const [deletingRunId, setDeletingRunId] = useState("");
  const [labelMode, setLabelMode] = useState<QualityLabelMode>(searchParams.get("mode") === "manual" ? "manual" : "automatic");
  const [datasetColumns, setDatasetColumns] = useState<Array<{ name: string; dtype: string }>>([]);
  const [loadingDatasetColumns, setLoadingDatasetColumns] = useState(false);
  const [targetColumnMode, setTargetColumnMode] = useState<"existing" | "new">("existing");
  const [targetColumn, setTargetColumn] = useState("");
  const [targetColumnDtype, setTargetColumnDtype] = useState<CreatedTargetColumnDtype>("int");
  const [qualityModels, setQualityModels] = useState<QualityModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [automaticSetupStep, setAutomaticSetupStep] = useState<1 | 2>(1);
  const [weakSupervision, setWeakSupervision] = useState(false);
  const [labelDtype, setLabelDtype] = useState<CreatedTargetColumnDtype>("string");
  const [annotationRules, setAnnotationRules] = useState<AnnotationRule[]>([
    { id: "rule-1", label: "", tokens: [
      { kind: "data", value: "" },
      { kind: "logical_operator", value: ">" },
      { kind: "number", value: "" },
    ] },
  ]);
  const [editingRuleToken, setEditingRuleToken] = useState<{ ruleId: string; tokenIndex: number } | null>({ ruleId: "rule-1", tokenIndex: 0 });
  const [clusterPreview, setClusterPreview] = useState<QualityClusterPreview | null>(null);
  const [previewingClusters, setPreviewingClusters] = useState(false);
  const clusterChartRef = useRef<HTMLDivElement>(null);
  const [workspaceMode, setWorkspaceMode] = useState(Boolean(searchParams.get("runId")));
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const activeContextRef = useRef({ projectId, runId });
  const detailRequestId = useRef(0);
  const runsRequestId = useRef(0);
  const skipUrlStateSyncRef = useRef(false);
  activeContextRef.current = { projectId, runId };

  const isCurrentContext = (expectedProjectId: string, expectedRunId: string) => (
    activeContextRef.current.projectId === expectedProjectId
    && activeContextRef.current.runId === expectedRunId
  );

  const selectedProject = useMemo(() => projects.find((item) => item.id === projectId), [projects, projectId]);
  const selectedModel = useMemo(
    () => qualityModels.find((item) => item.id === selectedModelId),
    [qualityModels, selectedModelId],
  );
  const selectedRun = runs.find((item) => item.id === runId);
  const selectedRunLabelSchemaKey = [
    selectedRun?.id || "",
    selectedRun?.label_mode || "",
    selectedRun?.target_schema?.name || "",
    selectedRun?.target_schema?.dtype || "",
    ...(selectedRun?.target_schema?.classes || []),
  ].join("\u0000");
  const labelOptionsStyle = useMemo(() => {
    const longestLabelLength = labelOptions.reduce((length, [, text]) => Math.max(length, Array.from(text).length), 0);
    return { "--label-option-width": `calc(${Math.max(longestLabelLength, 4)}ch + 68px)` } as CSSProperties;
  }, [labelOptions]);
  const requestedView = searchParams.get("view");
  const requestedRunId = searchParams.get("runId");
  const isWorkspace = workspaceMode || requestedView === "workspace";
  const isTaskList = !isWorkspace && (
    requestedView === "tasks"
    || (!searchParams.get("datasetId") && !searchParams.get("runId") && !requestedView)
  );
  const isSetup = !isWorkspace && !isTaskList;
  const projectRole = selectedProject?.project_role || "";
  const canCreate = ["owner", "editor"].includes(projectRole);
  const canLabel = ["owner", "editor", "operator"].includes(projectRole);

  useEffect(() => {
    setLabelOptions(labelOptionsForRun(selectedRun));
    setEditingLabelList(false);
    setNewLabelText("");
  }, [selectedRunLabelSchemaKey]);

  useEffect(() => {
    setLabelMode(searchParams.get("mode") === "manual" ? "manual" : "automatic");
  }, [searchParams]);

  useEffect(() => {
    if (!isSetup || !projectId || !datasetArtifactId) {
      setDatasetColumns([]);
      setLoadingDatasetColumns(false);
      setTargetColumn("");
      return;
    }
    let active = true;
    setLoadingDatasetColumns(true);
    listQualityDatasetColumns(projectId, datasetArtifactId)
      .then((result) => {
        if (!active) return;
        const columns = Array.isArray(result?.columns) ? result.columns : [];
        setDatasetColumns(columns);
        setTargetColumn((current) => (
          targetColumnMode === "existing" && columns.some((item) => item.name === current)
            ? current
            : ""
        ));
      })
      .catch((error) => { if (active) message.error(formatApiError(error, "数据列加载失败")); })
      .finally(() => { if (active) setLoadingDatasetColumns(false); });
    return () => { active = false; };
  }, [isSetup, projectId, datasetArtifactId, targetColumnMode, message]);

  useEffect(() => {
    if (targetColumnMode !== "existing" || !targetColumn) return;
    const selectedColumn = datasetColumns.find((column) => column.name === targetColumn);
    if (selectedColumn) setLabelDtype(normalizeLabelDtype(selectedColumn.dtype));
  }, [datasetColumns, targetColumn, targetColumnMode]);

  useEffect(() => {
    if (!isSetup || labelMode !== "automatic" || !projectId) {
      setQualityModels([]);
      setSelectedModelId("");
      return;
    }
    let active = true;
    listQualityModels(projectId)
      .then((items) => {
        if (!active) return;
        const models = Array.isArray(items) ? items : [];
        setQualityModels(models);
        setSelectedModelId((current) => models.some((item) => item.id === current) ? current : "");
      })
      .catch((error) => { if (active) message.error(formatApiError(error, "注册模型加载失败")); });
    return () => { active = false; };
  }, [isSetup, labelMode, projectId, message]);

  useEffect(() => {
    setClusterPreview(null);
    setPreviewingClusters(false);
  }, [datasetArtifactId, selectedModelId]);

  useEffect(() => {
    if (!clusterPreview || !clusterChartRef.current) return undefined;
    const chart = echarts.init(clusterChartRef.current);
    const clusterIds = [...new Set(clusterPreview.cluster_ids)].sort((left, right) => left - right);
    chart.setOption({
      tooltip: { trigger: "item" },
      legend: { data: clusterIds.map((clusterId) => `簇${clusterId}`), bottom: 0 },
      xAxis: { type: "value", name: "PC1" },
      yAxis: { type: "value", name: "PC2" },
      series: clusterIds.map((clusterId) => ({
        name: `簇${clusterId}`,
        type: "scatter",
        symbolSize: 7,
        itemStyle: { color: clusterColor(clusterId) },
        data: clusterPreview.pca_coordinates
          .map((point, index) => ({ point, clusterId: clusterPreview.cluster_ids[index] }))
          .filter((item) => item.clusterId === clusterId)
          .map((item) => [item.point[0], item.point[1], item.clusterId]),
        encode: { x: 0, y: 1, itemName: 2 },
      })),
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [clusterPreview]);

  useEffect(() => {
    let active = true;
    apiClient.get("/projects")
      .then((response) => {
        if (!active) return;
        const items = (response.data.items || response.data || []) as ProjectOption[];
        setProjects(items);
        setProjectId((current) => items.some((item) => item.id === current) ? current : isTaskList ? "" : items[0]?.id || "");
      })
      .catch(() => { if (active) setProjects([]); })
      .finally(() => { if (active) setLoadingProjects(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (isSetup && !loadingProjects && !projectId && projects[0]) setProjectId(projects[0].id);
  }, [isSetup, loadingProjects, projectId, projects]);

  useEffect(() => {
    if (loadingProjects) {
      runsRequestId.current += 1;
      setRuns([]);
      return;
    }
    let active = true;
    const requestId = ++runsRequestId.current;
    setLoadingRuns(true);
    const taskListMode = isTaskList;
    const expectedProjectId = projectId;
    const loadRuns = taskListMode
      ? listQualityRuns(projectId || undefined)
      : projectId && projects.some((project) => project.id === projectId)
        ? listQualityRuns(projectId)
        : Promise.resolve([] as QualityRun[]);
    loadRuns
      .then((items) => {
        if (!active || runsRequestId.current !== requestId || (!taskListMode && activeContextRef.current.projectId !== expectedProjectId)) return;
        const uniqueItems = Array.from(new Map(items.map((item) => [item.id, item])).values())
          .sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")));
        setRuns(uniqueItems);
        setRunId((current) => {
          if (uniqueItems.some((run) => run.id === current)) return current;
          return requestedRunId && uniqueItems.some((run) => run.id === requestedRunId) ? requestedRunId : "";
        });
      })
      .catch((error) => {
        if (active && runsRequestId.current === requestId && (taskListMode || activeContextRef.current.projectId === expectedProjectId)) {
          message.error(formatApiError(error, "标注任务加载失败"));
        }
      })
      .finally(() => {
        if (active && runsRequestId.current === requestId && (taskListMode || activeContextRef.current.projectId === expectedProjectId)) {
          setLoadingRuns(false);
        }
      });
    return () => { active = false; };
  }, [isTaskList, loadingProjects, projects, projectId, message, requestedRunId]);

  useEffect(() => {
    if (!isSetup || loadingProjects || !projectId) {
      setDatasets([]);
      return;
    }
    let active = true;
    setLoadingDatasets(true);
    listDatasets(projectId)
      .then((items) => {
        if (!active) return;
        const compatible = (items as DatasetOption[]).filter((item) => {
          const format = String(item.format || item.name?.split(".").pop() || "").toLowerCase();
          return ["csv", "xls", "xlsx"].includes(format);
        });
        setDatasets(compatible);
      })
      .catch((error) => {
        if (active) message.error(formatApiError(error, "数据管理文件加载失败"));
      })
      .finally(() => { if (active) setLoadingDatasets(false); });
    return () => { active = false; };
  }, [isSetup, requestedView, loadingProjects, projectId, message]);

  useEffect(() => {
    if (skipUrlStateSyncRef.current) {
      skipUrlStateSyncRef.current = false;
      return;
    }
    if (requestedView === "tasks") {
      if (workspaceMode) setWorkspaceMode(false);
      if (runId) setRunId("");
      if (datasetArtifactId) setDatasetArtifactId("");
      setSelected(null);
      setLabel("");
      setSearchParams((current) => {
        current.delete("type");
        current.set("view", "tasks");
        current.delete("runId");
        current.delete("sampleId");
        current.delete("datasetId");
        current.delete("mode");
        return current;
      }, { replace: true });
      return;
    }
    setSearchParams((current) => {
      if (projectId) current.set("projectId", projectId); else current.delete("projectId");
      if (datasetArtifactId) current.set("datasetId", datasetArtifactId); else current.delete("datasetId");
      if (runId) current.set("runId", runId); else current.delete("runId");
      return current;
    }, { replace: true });
  }, [projectId, datasetArtifactId, runId, requestedView, workspaceMode, setSearchParams]);

  useEffect(() => {
    detailRequestId.current += 1;
    if (!projectId || !runId) { setSamples([]); setSelected(null); setLoadingDetail(false); return; }
    let active = true;
    setLoadingSamples(true);
    setSelected(null);
    listQualitySamples(projectId, runId)
      .then((items) => { if (active) setSamples(items); })
      .catch((error) => { if (active) message.error(formatApiError(error, "样本队列加载失败")); })
      .finally(() => { if (active) setLoadingSamples(false); });
    return () => { active = false; };
  }, [projectId, runId, selectedRun?.status, message]);

  const selectSample = async (sample: QualitySample) => {
    if (!projectId || !runId) return;
    const expectedProjectId = projectId;
    const expectedRunId = runId;
    const requestId = ++detailRequestId.current;
    setLoadingDetail(true);
    try {
      const detail = await getQualitySample(projectId, runId, sample.id);
      if (detailRequestId.current !== requestId || !isCurrentContext(expectedProjectId, expectedRunId)) return;
      setSelected(detail);
      setLabel(detail.current_label || "");
    } catch (error) {
      if (detailRequestId.current === requestId && isCurrentContext(expectedProjectId, expectedRunId)) {
        message.error(formatApiError(error, "样本详情加载失败"));
      }
    } finally {
      if (detailRequestId.current === requestId && isCurrentContext(expectedProjectId, expectedRunId)) {
        setLoadingDetail(false);
      }
    }
  };

  useEffect(() => {
    const requestedSampleId = searchParams.get("sampleId");
    if (!requestedSampleId || selected?.id === requestedSampleId) return;
    const requestedSample = samples.find((sample) => sample.id === requestedSampleId);
    if (requestedSample) void selectSample(requestedSample);
  }, [samples, selected?.id, searchParams]);

  const refreshSamples = async (sampleId: string) => {
    if (!projectId || !runId) return;
    const expectedProjectId = projectId;
    const expectedRunId = runId;
    const items = await listQualitySamples(expectedProjectId, expectedRunId);
    if (!isCurrentContext(expectedProjectId, expectedRunId)) return;
    setSamples(items);
    const refreshed = items.find((item) => item.id === sampleId);
    if (refreshed) await selectSample(refreshed);
  };

  const previewAnnotationClusters = async () => {
    if (!projectId || !datasetArtifactId || !selectedModelId || previewingClusters) return;
    setPreviewingClusters(true);
    try {
      const preview = await previewQualityClusters(projectId, {
        dataset_artifact_id: datasetArtifactId,
        selected_model_id: selectedModelId,
      });
      setClusterPreview(preview);
      message.success(`聚类完成，最优 K=${preview.best_k}`);
    } catch (error) {
      setClusterPreview(null);
      message.error(formatApiError(error, "聚类失败"));
    } finally {
      setPreviewingClusters(false);
    }
  };

  const updateAnnotationRule = (ruleId: string, patch: Partial<AnnotationRule>) => {
    setAnnotationRules((current) => current.map((rule) => rule.id === ruleId ? { ...rule, ...patch } : rule));
  };

  const updateAnnotationRuleToken = (ruleId: string, tokenIndex: number, patch: Partial<AnnotationRuleToken>) => {
    setAnnotationRules((current) => current.map((rule) => rule.id === ruleId
      ? { ...rule, tokens: rule.tokens.map((token, index) => index === tokenIndex ? { ...token, ...patch } : token) }
      : rule));
  };

  const completeAnnotationRuleToken = (ruleId: string, tokenIndex: number, value: string) => {
    updateAnnotationRuleToken(ruleId, tokenIndex, { value });
    if (value !== "") setEditingRuleToken(null);
  };

  const addAnnotationRuleToken = (ruleId: string) => {
    const tokenIndex = annotationRules.find((rule) => rule.id === ruleId)?.tokens.length || 0;
    setAnnotationRules((current) => current.map((rule) => rule.id === ruleId
      ? { ...rule, tokens: [...rule.tokens, { kind: rule.tokens.length % 2 === 0 ? "number" : "logical_operator", value: "" }] }
      : rule));
    setEditingRuleToken({ ruleId, tokenIndex });
  };

  const removeAnnotationRuleToken = (ruleId: string, tokenIndex: number) => {
    setAnnotationRules((current) => current.map((rule) => rule.id === ruleId
      ? { ...rule, tokens: rule.tokens.filter((_, index) => index !== tokenIndex) }
      : rule));
    setEditingRuleToken(null);
  };

  const removeAnnotationRule = (ruleId: string) => setAnnotationRules((current) => current.filter((rule) => rule.id !== ruleId));

  const addAnnotationRule = () => setAnnotationRules((current) => [...current, {
    id: `rule-${Date.now()}`,
    label: "",
    tokens: [{ kind: "data", value: "" }, { kind: "logical_operator", value: ">" }, { kind: "number", value: "" }],
  }]);

  const serializedAnnotationRules = (): AnnotationProcessRule[] => annotationRules.map((rule) => ({
    id: rule.id,
    label: rule.label,
    tokens: rule.tokens.map((token) => ({ kind: token.kind, value: token.value })),
  }));

  const weakSupervisionRulesAreValid = (dtype: CreatedTargetColumnDtype = labelDtype) => {
    if (!weakSupervision) return true;
    if (!clusterPreview) {
      message.error("请先完成聚类");
      return false;
    }
    const operandKinds = new Set<AnnotationRuleTokenKind>(["data", "number", "string"]);
    const operatorKinds = new Set<AnnotationRuleTokenKind>(["number_operator", "logical_operator"]);
    for (const rule of annotationRules) {
      const rawLabel = rule.label.trim();
      const labelNumber = Number(rawLabel);
      const validLabel = dtype === "int"
        ? rawLabel !== "" && Number.isFinite(labelNumber) && Number.isInteger(labelNumber)
        : dtype === "float"
          ? rawLabel !== "" && Number.isFinite(labelNumber)
          : rawLabel !== "";
      const validTokens = rule.tokens.length >= 3
        && rule.tokens.every((token, index) => token.value !== "" && (index % 2 === 0 ? operandKinds : operatorKinds).has(token.kind))
        && operandKinds.has(rule.tokens[rule.tokens.length - 1].kind)
        && rule.tokens.some((token) => token.kind === "logical_operator" && !["and", "or"].includes(token.value));
      if (!validLabel || !validTokens) {
        message.error("请检查标注规则和标签数据类型");
        return false;
      }
    }
    return annotationRules.length > 0;
  };

  const startQualityRun = async (
    nextDatasetArtifactId: string,
    nextLabelMode: QualityLabelMode = labelMode,
  ) => {
    const normalizedTargetColumn = nextLabelMode === "automatic" ? undefined : targetColumn.trim();
    if (!projectId || (nextLabelMode === "manual" && !normalizedTargetColumn)) return;
    const targetColumnCreated = nextLabelMode === "automatic"
      ? false
      : targetColumnMode === "new";
    const modelLabelDtype = selectedModel?.label_dtype?.toLowerCase().includes("float")
      ? "float"
      : selectedModel?.label_dtype?.toLowerCase().includes("int")
        ? "int"
        : "string";
    const effectiveLabelDtype = nextLabelMode === "automatic"
      ? (weakSupervision ? labelDtype : modelLabelDtype)
      : targetColumnCreated
        ? targetColumnDtype
        : normalizeLabelDtype(datasetColumns.find((column) => column.name === normalizedTargetColumn)?.dtype);
    if (nextLabelMode === "automatic" && weakSupervision && !weakSupervisionRulesAreValid(effectiveLabelDtype)) return;
    const inputColumns = datasetColumns.map((item) => item.name).filter((name) => name !== normalizedTargetColumn);
    const validation = await validateQualityDataset(projectId, nextDatasetArtifactId, {}, {
      label_mode: nextLabelMode,
      workflow_kind: "data_annotation",
      algorithm_ids: [],
      search_method: "bayesian",
      max_trials: 20,
      time_budget: 600,
      ...(nextLabelMode === "manual" ? {
        target_column: normalizedTargetColumn,
        target_column_created: targetColumnCreated,
        target_column_dtype: targetColumnCreated ? effectiveLabelDtype : undefined,
        input_columns: inputColumns,
      } : { label_dtype: effectiveLabelDtype }),
      selected_model_id: nextLabelMode === "automatic" ? selectedModelId : undefined,
      weak_supervision: nextLabelMode === "automatic" ? weakSupervision : undefined,
      process_rules: nextLabelMode === "automatic" && weakSupervision ? serializedAnnotationRules() : undefined,
      cluster_labels: nextLabelMode === "automatic" && weakSupervision
        ? Object.fromEntries((clusterPreview?.cluster_summaries || []).map((item) => [String(item.cluster_id), item.role]))
        : undefined,
    });
    if (!validation.valid_rows || validation.errors.length) {
      const firstError = validation.errors[0];
      message.error(firstError?.code || "数据校验失败");
      return;
    }
    const payload: Parameters<typeof createQualityRun>[1] = {
      dataset_artifact_id: nextDatasetArtifactId,
      field_mapping: {},
      algorithm_ids: [],
      search_method: "bayesian",
      max_trials: 20,
      time_budget: 600,
      label_mode: nextLabelMode,
      workflow_kind: "data_annotation",
      ...(nextLabelMode === "manual" ? {
        target_column: normalizedTargetColumn,
        target_column_created: targetColumnCreated,
        ...(targetColumnCreated ? { target_column_dtype: effectiveLabelDtype } : {}),
        input_columns: inputColumns,
      } : { label_dtype: effectiveLabelDtype }),
    };
    if (nextLabelMode === "automatic") {
      payload.selected_model_id = selectedModelId;
      payload.weak_supervision = weakSupervision;
      payload.process_rules = weakSupervision ? serializedAnnotationRules() : undefined;
      payload.cluster_labels = weakSupervision
        ? Object.fromEntries((clusterPreview?.cluster_summaries || []).map((item) => [String(item.cluster_id), item.role]))
        : undefined;
    }
    const run = await createQualityRun(projectId, payload);
    const taskListParams = new URLSearchParams();
    taskListParams.set("view", "tasks");
    taskListParams.set("projectId", run.project_id || projectId);
    taskListParams.set("mode", nextLabelMode);
    const workspaceParams = new URLSearchParams(taskListParams);
    workspaceParams.set("view", "workspace");
    workspaceParams.set("datasetId", nextDatasetArtifactId);
    workspaceParams.set("runId", run.id);
    navigate(`/data-annotation?${taskListParams.toString()}`, { replace: true });
    navigate(`/data-annotation?${workspaceParams.toString()}`);
    setWorkspaceMode(true);
    setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
    setRunId(run.id);
    setDatasetArtifactId(nextDatasetArtifactId);
    setSamples([]);
    setSelected(null);
    message.success(`${nextLabelMode === "automatic" ? "自动标注" : "手动标注"}任务已创建，共 ${validation.valid_rows} 条记录`);
  };

  const handleReportUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !projectId || !canCreate) return;
    const extension = file.name.split(".").pop()?.toLowerCase();
    if (!extension || !["csv", "xls", "xlsx"].includes(extension)) {
      message.error("仅支持 CSV、XLS 或 XLSX 数据文件");
      return;
    }
    setPreparingRun(true);
    try {
      const artifact = await uploadQualityDataset(projectId, file);
      setDatasetArtifactId(artifact.artifact_id);
      setWorkspaceMode(false);
      setSearchParams((current) => {
        current.delete("type");
        current.set("projectId", projectId);
        current.set("datasetId", artifact.artifact_id);
        current.delete("runId");
        current.set("mode", labelMode);
        return current;
      }, { replace: true });
      message.success("数据文件已上传，请继续配置标注任务");
    } catch (error) {
      message.error(formatApiError(error, "数据文件上传失败"));
    } finally {
      setPreparingRun(false);
    }
  };

  const handleSelectedDataset = async () => {
    if (!datasetArtifactId || !canCreate) return;
    if (labelMode === "automatic" && !weakSupervisionRulesAreValid()) return;
    setPreparingRun(true);
    try {
      await startQualityRun(datasetArtifactId, labelMode);
    } catch (error) {
      message.error(formatApiError(error, "标注任务创建失败"));
    } finally {
      setPreparingRun(false);
    }
  };

  const openSetup = (nextMode: QualityLabelMode = "automatic") => {
    setWorkspaceMode(false);
    setRunId("");
    setLabelMode(nextMode);
    setAutomaticSetupStep(1);
    setSearchParams((current) => {
      current.delete("type");
      current.set("view", "setup");
      current.set("mode", nextMode);
      current.delete("runId");
      return current;
    }, { replace: true });
  };

  const returnToTaskList = () => {
    detailRequestId.current += 1;
    skipUrlStateSyncRef.current = true;
    setWorkspaceMode(false);
    setDatasetArtifactId("");
    setRunId("");
    setSelected(null);
    setLabel("");
    const next = new URLSearchParams();
    next.set("view", "tasks");
    if (projectId) next.set("projectId", projectId);
    next.set("mode", labelMode);
    setSearchParams(next, { replace: true });
  };

  const openRunWorkspace = (run: QualityRun, mode: QualityLabelMode = run.label_mode || "automatic") => {
    skipUrlStateSyncRef.current = true;
    setWorkspaceMode(true);
    if (run.project_id) setProjectId(run.project_id);
    setRunId(run.id);
    setLabelMode(mode);
      setSearchParams((current) => {
      current.delete("type");
      current.set("view", "workspace");
      current.set("projectId", projectId);
      current.set("runId", run.id);
      current.set("mode", mode);
      return current;
    }, { replace: true });
  };

  const refreshRuns = async () => {
    const expectedProjectId = projectId;
    const requestId = ++runsRequestId.current;
    setLoadingRuns(true);
    try {
      const items = await listQualityRuns(expectedProjectId || undefined);
      if (runsRequestId.current !== requestId || activeContextRef.current.projectId !== expectedProjectId) return;
      setRuns(items);
    } catch (error) {
      if (runsRequestId.current === requestId && activeContextRef.current.projectId === expectedProjectId) {
        message.error(formatApiError(error, "标注任务加载失败"));
      }
    } finally {
      if (runsRequestId.current === requestId && activeContextRef.current.projectId === expectedProjectId) {
        setLoadingRuns(false);
      }
    }
  };

  const saveLabel = async (nextLabel: string) => {
    if (!projectId || !runId || !selected || !nextLabel || savingLabel) return;
    const normalizedLabel = normalizeLabelValue(nextLabel, selectedRun);
    if (!normalizedLabel) {
      message.error(`标签必须符合 ${selectedRun?.target_schema?.dtype || "目标列"} 类型`);
      return;
    }
    const sampleId = selected.id;
    const previousLabel = label;
    setLabel(normalizedLabel);
    setSavingLabel(true);
    try {
      const saved = await submitQualityLabel(projectId, runId, sampleId, { label: normalizedLabel, note: "" });
      setSelected((current) => current?.id === sampleId ? { ...current, ...saved } : current);
      setSamples((current) => current.map((sample) => sample.id === sampleId ? { ...sample, ...saved } : sample));
      await refreshActiveWorkspace();
      message.success("标签已保存");
    } catch (error) {
      setLabel(previousLabel);
      message.error(formatApiError(error, "标签保存失败"));
    } finally {
      setSavingLabel(false);
    }
  };

  const addLabelOption = () => {
    const text = newLabelText.trim();
    if (!text) return;
    const normalized = normalizeLabelValue(text, selectedRun);
    if (!normalized) {
      message.error(`标签必须符合 ${selectedRun?.target_schema?.dtype || "目标列"} 类型`);
      return;
    }
    const value = selectedRun?.label_mode === "manual" && selectedRun.target_schema
      ? normalized
      : text.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || `custom_${labelOptions.length + 1}`;
    if (labelOptions.some(([currentValue, currentText]) => currentValue === value || currentText === normalized)) {
      message.warning("标签已存在");
      return;
    }
    setLabelOptions((current) => [...current, [value, normalized]]);
    setNewLabelText("");
  };

  const removeLabelOption = (value: string, text: string) => {
    if (label === value) {
      message.warning("当前样本已使用该标签，请先更换样本标签");
      return;
    }
    setLabelOptions((current) => current.filter(([currentValue]) => currentValue !== value));
    message.success(`已从标签列表移除“${text}”`);
  };

  const refreshActiveWorkspace = async () => {
    if (!projectId || !runId) return;
    const expectedProjectId = projectId;
    const expectedRunId = runId;
    const [latestRun, latestSamples] = await Promise.all([
      getQualityRun(expectedProjectId, expectedRunId),
      listQualitySamples(expectedProjectId, expectedRunId),
    ]);
    if (!isCurrentContext(expectedProjectId, expectedRunId)) return;
    setRuns((current) => current.map((item) => item.id === latestRun.id ? latestRun : item));
    setSamples(latestSamples);
    const selectedSample = selected && latestSamples.find((item) => item.id === selected.id);
    if (selectedSample) {
      setSelected((current) => current?.id === selectedSample.id ? { ...current, ...selectedSample } : current);
      setLabel(selectedSample.current_label || "");
    }
  };

  const removeRun = async (run: QualityRun) => {
    const runProjectId = run.project_id || projectId;
    if (!runProjectId || deletingRunId) return;
    setDeletingRunId(run.id);
    try {
      await deleteQualityRun(runProjectId, run.id);
      setRuns((current) => current.filter((item) => item.id !== run.id));
      message.success("标注任务已删除");
    } catch (error) {
      message.error(formatApiError(error, "标注任务删除失败"));
    } finally {
      setDeletingRunId("");
    }
  };

  const downloadAnnotations = async (format: "csv" | "xlsx") => {
    if (!projectId || !runId) return;
    setDownloadingAnnotationExport(true);
    try {
      const blob = await downloadQualityAnnotationExport(projectId, runId, format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `data-annotations-${runId.slice(0, 8)}.${format}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      message.error(formatApiError(error, "标注导出失败"));
    } finally {
      setDownloadingAnnotationExport(false);
    }
  };

  const saveToDataManagement = async () => {
    if (!projectId || !runId || !canLabel) return;
    setSavingLabeledDataset(true);
    try {
      const saved = await saveLabeledDataset(projectId, runId, "current");
      message.success(`已保存到数据管理：${saved.name}`);
      navigate(`/data?projectId=${encodeURIComponent(projectId)}`);
    } catch (error) {
      message.error(formatApiError(error, "标注数据保存失败"));
    } finally {
      setSavingLabeledDataset(false);
    }
  };

  useEffect(() => {
    if (!projectId || !runId || !["queued", "validating", "running"].includes(String(selectedRun?.status || ""))) return;
    const timer = window.setInterval(() => {
      void refreshActiveWorkspace().catch((error) => message.error(formatApiError(error, "标注进度刷新失败")));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [projectId, runId, selectedRun?.status, selected?.id, message]);

  const taskColumns = [
    {
      title: copy.task,
      key: "task",
      render: (_: unknown, run: QualityRun) => <div className="table-primary-cell">
        <strong>{run.id.slice(0, 8)}</strong>
        <span>{runModeText(run, copy)}</span>
      </div>,
    },
    { title: copy.project, key: "project", render: (_: unknown, run: QualityRun) => run.project_name || run.project_id || "-" },
    { title: copy.creator, key: "creator", render: (_: unknown, run: QualityRun) => run.created_by_name || run.created_by_id || "-" },
    { title: copy.modeStatus, key: "status", render: (_: unknown, run: QualityRun) => <Tag color={taskStatusColor(run.status)}>{runStatusText(run, lang)}</Tag> },
    { title: copy.progress, key: "progress", render: (_: unknown, run: QualityRun) => annotationProgressText(run) },
    {
      title: copy.actions,
      key: "actions",
      align: "right" as const,
      render: (_: unknown, run: QualityRun) => <div className="table-row-actions">
        <TableRowAction
          label={`${run.label_mode === "manual" ? copy.viewManual : copy.view} ${run.id}`}
          icon={<EyeOutlined />}
          onClick={() => openRunWorkspace(run)}
        />
        <DeleteConfirmation
          label={`${copy.deleteTask} ${run.id}`}
          targetName={run.id}
          loading={deletingRunId === run.id}
          onConfirm={() => void removeRun(run)}
        />
      </div>,
    },
  ];

  const tasksView = (
    <>
      <div className="page-header data-annotation__tasks-header">
        <div className="page-header-copy">
          <h2 className="page-title">{copy.title}</h2>
        </div>
        <div className="data-annotation__task-actions">
          <select aria-label={copy.project} value={projectId} onChange={(event) => setProjectId(event.target.value)} disabled={loadingProjects}>
            <option value="">{lang === "zh" ? "全部项目" : "All projects"}</option>
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
          <button type="button" className="ant-btn" onClick={() => openSetup("manual")}>{copy.manualTask}</button>
          <button type="button" className="ant-btn ant-btn-primary" onClick={() => openSetup("automatic")}>{copy.automaticTask}</button>
        </div>
      </div>
      <div className="table-surface data-annotation__tasks-surface" role="region" aria-label={copy.taskListLabel}>
        <Table<QualityRun>
          rowKey="id"
          size="small"
          loading={loadingRuns}
          dataSource={runs}
          columns={taskColumns}
          pagination={false}
          scroll={{ x: 820 }}
          locale={{ emptyText: <Empty description={copy.noTasks} /> }}
        />
      </div>
    </>
  );

  const setupView = (
    <>
      <div className="page-header spot-weld-annotation__workspace-header">
        <div className="page-header-copy">
          <h2 className="page-title">{labelMode === "manual" ? copy.manualTask : copy.automaticTask}</h2>
          <p className="page-subtitle">{labelMode === "automatic" ? (lang === "zh" ? "选择数据和注册模型，再配置标注策略" : "Select data and a registered model, then configure the strategy") : (lang === "zh" ? "选择数据文件和必填目标列后创建任务" : "Select a data file and required target column to create the task")}</p>
        </div>
        <button type="button" className="ant-btn" onClick={returnToTaskList}>{copy.backToTasks}</button>
      </div>
      <section className="data-annotation__setup" aria-label={copy.setupLabel}>
        {labelMode === "automatic" && <Steps
          className="data-annotation__setup-steps"
          current={automaticSetupStep - 1}
          items={[{ title: copy.chooseModel }, { title: copy.weakTitle }]}
          responsive={false}
        />}
        {labelMode === "manual" || automaticSetupStep === 1 ? <>
        <div className="data-annotation__setup-grid">
          <div className="data-annotation__setup-field">
            <label htmlFor="spot-weld-setup-project">{copy.project}</label>
            <select id="spot-weld-setup-project" aria-label="Project" value={projectId} onChange={(event) => { setProjectId(event.target.value); setDatasetArtifactId(""); setRunId(""); }} disabled={loadingProjects}>
              <option value="">{copy.chooseProject}</option>
              {projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
            </select>
          </div>
          <div className="data-annotation__setup-field">
            <label htmlFor="spot-weld-dataset">{copy.dataFileLabel}</label>
            <select
              id="spot-weld-dataset"
              aria-label={copy.dataFileLabel}
              value={datasetArtifactId}
              onChange={(event) => {
                const next = event.target.value;
                setDatasetArtifactId(next);
                setSearchParams((current) => { if (next) current.set("datasetId", next); else current.delete("datasetId"); current.delete("runId"); return current; }, { replace: true });
              }}
              disabled={!projectId || loadingDatasets}
            >
              <option value="">{copy.chooseFile}</option>
              {datasets.map((dataset) => {
                const artifactId = dataset.artifact_id || dataset.id || "";
                return <option value={artifactId} key={artifactId}>{dataset.name || artifactId} · {dataset.row_count ?? 0} 行</option>;
              })}
            </select>
          </div>
        </div>
        <div className="data-annotation__source-actions">
          <input ref={uploadInputRef} className="spot-weld-annotation__sr-only" type="file" accept=".csv,.xls,.xlsx" aria-label={copy.uploadFile} onChange={handleReportUpload} />
          <button type="button" className="ant-btn" onClick={() => uploadInputRef.current?.click()} disabled={!canCreate || preparingRun}><UploadOutlined />{copy.uploadButton}</button>
        </div>
        {labelMode === "manual" && <div className="data-annotation__setup-grid">
          <div className="data-annotation__setup-field">
            <label htmlFor="quality-target-column-mode">目标列来源</label>
            <select id="quality-target-column-mode" aria-label="目标列来源" value={targetColumnMode} onChange={(event) => { setTargetColumnMode(event.target.value as "existing" | "new"); setTargetColumn(""); }}>
              <option value="existing">选择已有列</option>
              <option value="new">新建目标列</option>
            </select>
          </div>
          <div className="data-annotation__setup-field">
            <label htmlFor="quality-target-column">目标列</label>
            {targetColumnMode === "existing" ? <select id="quality-target-column" aria-label="目标列" value={targetColumn} onChange={(event) => setTargetColumn(event.target.value)} disabled={!datasetArtifactId}>
              <option value="">选择目标列</option>
              {datasetColumns.map((column) => <option key={column.name} value={column.name}>{column.name} · {column.dtype}</option>)}
            </select> : <input id="quality-target-column" aria-label="目标列" value={targetColumn} onChange={(event) => setTargetColumn(event.target.value)} placeholder="输入新目标列名称" />}
          </div>
          {targetColumnMode === "new" && <div className="data-annotation__setup-field">
            <label htmlFor="quality-target-column-dtype">数据类型</label>
            <select id="quality-target-column-dtype" aria-label="数据类型" value={targetColumnDtype} onChange={(event) => setTargetColumnDtype(event.target.value as CreatedTargetColumnDtype)}>
              {CREATED_TARGET_COLUMN_DTYPE_OPTIONS.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
            </select>
          </div>}
        </div>}
        {labelMode === "automatic" && <div className="data-annotation__setup-grid">
          <div className="data-annotation__setup-field">
            <label htmlFor="quality-registered-model">{copy.chooseModel}</label>
            <select id="quality-registered-model" aria-label={copy.chooseModel} value={selectedModelId} onChange={(event) => setSelectedModelId(event.target.value)}>
              <option value="">{copy.chooseModelOption}</option>
              {qualityModels.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.version || "v1"} · {model.framework || "-"}</option>)}
            </select>
          </div>
        </div>}
        {labelMode === "automatic" && <div className="data-annotation__setup-footer data-annotation__setup-footer--centered">
          <button type="button" className="ant-btn ant-btn-primary" onClick={() => setAutomaticSetupStep(2)} disabled={!canCreate || !projectId || !datasetArtifactId || !selectedModelId || loadingDatasetColumns}>
            {copy.next}<RightOutlined />
          </button>
        </div>}
        </> : <>
        <div className="data-annotation__setup-grid">
          <div className="data-annotation__setup-field">
            <label htmlFor="quality-annotation-strategy">标注策略</label>
            <select id="quality-annotation-strategy" aria-label="标注策略" value="model-inference" disabled>
              <option value="model-inference">注册模型推理</option>
            </select>
          </div>
          <div className="data-annotation__setup-field">
            <label htmlFor="quality-selected-model-summary">已选模型</label>
            <input id="quality-selected-model-summary" aria-label="已选模型" value={selectedModel ? `${selectedModel.name} · ${selectedModel.version || "v1"}` : "-"} readOnly />
          </div>
        </div>
        <section className="data-annotation__weak-supervision" aria-labelledby="annotation-weak-supervision-title">
          <div className="data-annotation__rules-head">
            <div>
              <h3 id="annotation-weak-supervision-title">{copy.weakTitle}</h3>
              <p>{copy.weakHint}</p>
            </div>
            <label className="data-annotation__toggle-field" htmlFor="annotation-weak-supervision-toggle">
              <input id="annotation-weak-supervision-toggle" aria-label={copy.weakTitle} type="checkbox" checked={weakSupervision} onChange={(event) => { setWeakSupervision(event.target.checked); setClusterPreview(null); }} />
              <span className="data-annotation__toggle-track" aria-hidden="true"><span className="data-annotation__toggle-thumb" /></span>
              <span>{weakSupervision ? copy.enabled : copy.enable}</span>
            </label>
          </div>
          {weakSupervision && <>
            <div className="data-annotation__weak-actions">
              <button type="button" className="ant-btn" onClick={() => void previewAnnotationClusters()} disabled={previewingClusters || !datasetArtifactId || !selectedModelId}>
                {previewingClusters ? <><span className="data-annotation__spinner" aria-hidden="true" />{copy.clustering}</> : copy.startClustering}
              </button>
              {clusterPreview && <Tag color="blue">最优 K：{clusterPreview.best_k} · {clusterPreview.feature_count || 0} 个特征</Tag>}
            </div>
            {previewingClusters && <div className="data-annotation__cluster-loading" role="status"><span className="data-annotation__spinner data-annotation__spinner--large" aria-hidden="true" />{copy.clusteringHint}</div>}
            {clusterPreview && <div className="data-annotation__cluster-result">
              <div className="data-annotation__cluster-summary" aria-label={copy.clusterResult}>
                {clusterPreview.cluster_summaries?.map((item) => <div className="data-annotation__cluster-summary-item" key={item.cluster_id}>
                  <span className="data-annotation__cluster-swatch" style={{ "--cluster-color": clusterColor(item.cluster_id) } as CSSProperties} aria-hidden="true" />
                  <span>{lang === "zh" ? `簇${item.cluster_id}（${item.role === "normal" ? copy.normal : copy.anomaly}）：${item.count}条（${item.percentage}%）` : `Cluster ${item.cluster_id} (${item.role === "normal" ? copy.normal : copy.anomaly}): ${item.count} ${copy.rows} (${item.percentage}%)`}</span>
                </div>)}
              </div>
              <div ref={clusterChartRef} className="data-annotation__cluster-chart" aria-label={copy.clusterChart} />
            </div>}
            {clusterPreview && <div className="data-annotation__annotation-rules" aria-label={lang === "zh" ? "标注规则列表" : copy.rulesTitle}>
              <div className="data-annotation__rules-head"><div><h3>{copy.rulesTitle}</h3><p>{copy.rulesHint}</p></div><button type="button" className="ant-btn" onClick={addAnnotationRule}>{copy.addRow}</button></div>
              <div className="data-annotation__label-type-row"><label htmlFor="annotation-label-dtype">{copy.labelType}</label><select id="annotation-label-dtype" aria-label={copy.labelType} value={labelDtype} onChange={(event) => setLabelDtype(event.target.value as CreatedTargetColumnDtype)}><option value="int">{copy.int}</option><option value="float">{copy.float}</option><option value="string">{copy.stringType}</option></select></div>
              {annotationRules.map((rule) => <div className="data-annotation__annotation-rule" key={rule.id}>
                <div className="data-annotation__annotation-rule-head"><strong>{copy.rule}</strong><Tooltip title={copy.deleteRule}><button type="button" className="ant-btn ant-btn-icon-only ant-btn-danger-icon" aria-label={lang === "zh" ? "删除" : `${copy.deleteRule} ${rule.id}`} onClick={() => removeAnnotationRule(rule.id)} disabled={annotationRules.length === 1}><DeleteOutlined /></button></Tooltip></div>
                <div className="data-annotation__rule-tokens">{rule.tokens.map((token, index) => {
                  const isEditing = token.value === "" || (editingRuleToken?.ruleId === rule.id && editingRuleToken.tokenIndex === index);
                  return <div className={`data-annotation__rule-token ${isEditing ? "is-editing" : "is-complete"}`} key={`${rule.id}-${index}`}>
                    {isEditing ? <>
                      <select aria-label={lang === "zh" ? `规则 ${rule.id} 条件 ${index + 1} 类型` : `${copy.editCondition} ${index + 1}`} value={token.kind} onFocus={() => setEditingRuleToken({ ruleId: rule.id, tokenIndex: index })} onChange={(event) => updateAnnotationRuleToken(rule.id, index, { kind: event.target.value as AnnotationRuleTokenKind, value: "" })}>
                        <option value="data">{copy.data}</option><option value="number_operator">{copy.numberOperator}</option><option value="logical_operator">{copy.logicalOperator}</option><option value="number">{copy.number}</option><option value="string">{copy.string}</option>
                      </select>
                      {token.kind === "data" ? <select aria-label={lang === "zh" ? `规则 ${rule.id} 条件 ${index + 1} 值` : copy.chooseData} value={token.value} onFocus={() => setEditingRuleToken({ ruleId: rule.id, tokenIndex: index })} onChange={(event) => completeAnnotationRuleToken(rule.id, index, event.target.value)}><option value="">{copy.chooseData}</option>{datasetColumns.map((column) => <option value={column.name} key={column.name}>{column.name}</option>)}</select>
                        : token.kind === "number_operator" ? <select aria-label={lang === "zh" ? `规则 ${rule.id} 条件 ${index + 1} 值` : copy.chooseOperator} value={token.value} onFocus={() => setEditingRuleToken({ ruleId: rule.id, tokenIndex: index })} onChange={(event) => completeAnnotationRuleToken(rule.id, index, event.target.value)}><option value="">{copy.chooseOperator}</option>{["+", "-", "*", "/"].map((value) => <option value={value} key={value}>{value}</option>)}</select>
                          : token.kind === "logical_operator" ? <select aria-label={lang === "zh" ? `规则 ${rule.id} 条件 ${index + 1} 值` : copy.chooseLogic} value={token.value} onFocus={() => setEditingRuleToken({ ruleId: rule.id, tokenIndex: index })} onChange={(event) => completeAnnotationRuleToken(rule.id, index, event.target.value)}><option value="">{copy.chooseLogic}</option>{[">", ">=", "<", "<=", "==", "!=", "and", "or"].map((value) => <option value={value} key={value}>{value}</option>)}</select>
                            : <input aria-label={lang === "zh" ? `规则 ${rule.id} 条件 ${index + 1} 值` : copy.editCondition} type={token.kind === "number" ? "number" : "text"} value={token.value} onFocus={() => setEditingRuleToken({ ruleId: rule.id, tokenIndex: index })} onChange={(event) => updateAnnotationRuleToken(rule.id, index, { value: event.target.value })} onBlur={() => token.value !== "" && setEditingRuleToken(null)} onKeyDown={(event) => { if (event.key === "Enter" && token.value !== "") { event.preventDefault(); setEditingRuleToken(null); } }} placeholder={token.kind === "number" ? copy.inputNumber : copy.inputString} />}
                    </> : <button type="button" className="data-annotation__rule-token-value" aria-label={lang === "zh" ? `编辑条件 ${index + 1}：${token.value}` : `${copy.editCondition} ${index + 1}: ${token.value}`} onClick={() => setEditingRuleToken({ ruleId: rule.id, tokenIndex: index })}>{token.value}</button>}
                    <Tooltip title={copy.deleteCondition}><button type="button" className="data-annotation__rule-token-delete" aria-label={lang === "zh" ? `删除条件 ${index + 1}` : `${copy.deleteCondition} ${index + 1}`} onClick={() => removeAnnotationRuleToken(rule.id, index)}>×</button></Tooltip>
                  </div>;
                })}<button type="button" className="ant-btn ant-btn-sm" onClick={() => addAnnotationRuleToken(rule.id)}>{copy.addCondition}</button></div>
                <div className="data-annotation__annotation-rule-label"><label htmlFor={`annotation-rule-label-${rule.id}`}>{copy.hitLabel}</label><input id={`annotation-rule-label-${rule.id}`} aria-label={lang === "zh" ? `规则 ${rule.id} 标签` : `${copy.rule} ${rule.id} ${copy.hitLabel}`} value={rule.label} onChange={(event) => updateAnnotationRule(rule.id, { label: event.target.value })} placeholder={copy.inputLabel} /></div>
              </div>)}
            </div>}
          </>}
        </section>
        <div className="data-annotation__setup-footer data-annotation__setup-footer--centered">
          <button type="button" className="ant-btn" onClick={() => setAutomaticSetupStep(1)} disabled={preparingRun}><LeftOutlined />{copy.previous}</button>
          <button type="button" className="ant-btn ant-btn-primary" onClick={() => void handleSelectedDataset()} disabled={!canCreate || !projectId || !datasetArtifactId || !selectedModelId || preparingRun}>
            {preparingRun ? copy.preparing : copy.startAutomatic}
          </button>
        </div>
        </>}
        {labelMode === "manual" && <div className="data-annotation__setup-footer">
          <button type="button" className="ant-btn ant-btn-primary" onClick={() => void handleSelectedDataset()} disabled={!canCreate || !projectId || !datasetArtifactId || !targetColumn.trim() || preparingRun}>
            {preparingRun ? copy.preparing : copy.startManual}
          </button>
        </div>}
      </section>
    </>
  );

  const workspaceView = (
    <>
      <div className="page-header spot-weld-annotation__workspace-header">
        <div className="page-header-copy">
          <p className="page-kicker">DATA / LABELING</p>
          <h2 className="page-title">{t.spotWeld.title}</h2>
          <p className="page-subtitle">{selectedProject?.name || (lang === "zh" ? "样本逐条标注" : "Review samples one by one")}</p>
        </div>
        <div className="spot-weld-annotation__actions">
          <button type="button" className="ant-btn" aria-label={copy.backToTasks} onClick={returnToTaskList}>{copy.backToTasks}</button>
          {projectId && selectedRun && <Dropdown trigger={["click"]} disabled={downloadingAnnotationExport} menu={{ items: [{ key: "csv", label: "CSV" }, { key: "xlsx", label: "XLSX" }], onClick: ({ key }) => { void downloadAnnotations(key as "csv" | "xlsx"); } }}>
            <button type="button" className="ant-btn" aria-label={copy.export} disabled={downloadingAnnotationExport}><DownloadOutlined />{copy.export}</button>
          </Dropdown>}
          {projectId && selectedRun?.status === "completed" && <button type="button" className="ant-btn" aria-label={copy.saveToData} onClick={() => void saveToDataManagement()} disabled={!canLabel || savingLabeledDataset}>{savingLabeledDataset ? copy.saving : copy.saveToData}</button>}
          <Tooltip title={copy.refreshTasks}><button type="button" className="ant-btn ant-btn-icon-only" aria-label={copy.refreshTasks} onClick={() => { void refreshRuns(); }} disabled={loadingRuns}><ReloadOutlined /></button></Tooltip>
        </div>
      </div>
      <div className="spot-weld-annotation__workspace spot-weld-annotation__workspace--detail">
        <section className="spot-weld-annotation__region spot-weld-annotation__queue" aria-labelledby="spot-weld-queue-title">
          <div className="spot-weld-annotation__region-head"><h3 id="spot-weld-queue-title">{copy.sampleQueue}</h3><div className="spot-weld-annotation__queue-meta"><Tag>{samples.length} {copy.rows}</Tag>{selectedRun && <Tag color="blue">{annotationProgressText(selectedRun)}</Tag>}</div></div>
          {loadingRuns || loadingSamples ? <Spin /> : samples.length === 0 ? <Empty description={copy.noSamples} /> : (
            <div className="spot-weld-annotation__sample-list">
              {samples.map((sample) => <button type="button" className={`spot-weld-annotation__sample ${selected?.id === sample.id ? "is-selected" : ""}`} key={sample.id} onClick={() => selectSample(sample)} aria-label={sample.display_id}>
                <span><strong>{sample.display_id}</strong><small>{copy.row.replace("{index}", String(sample.source_row_index ?? "-"))}</small></span>
                <Tag color={selectedRun?.label_mode === "manual" ? undefined : warningColor[sample.warning_level || "none"]}>{qualityLabelText(sample.current_label || sample.automatic_label) || copy.unlabelled}</Tag>
              </button>)}
            </div>
          )}
        </section>
        <section className="spot-weld-annotation__region spot-weld-annotation__detail" aria-labelledby="spot-weld-detail-title">
          <div className="spot-weld-annotation__region-head"><h3 id="spot-weld-detail-title">{copy.sampleDetail}</h3>{selectedRun && <Tag color={taskStatusColor(selectedRun.status)}>{runStatusText(selectedRun, lang)}</Tag>}</div>
          {loadingDetail ? <Spin /> : !selected ? <Empty description={copy.selectSample} /> : <>
            <section className="spot-weld-annotation__label-editor" aria-label={copy.humanLabel}>
              <div className="spot-weld-annotation__label-head">
                <div className="spot-weld-annotation__subhead"><h4>{labelHeadingForRun(selectedRun, copy)}</h4><small>{savingLabel ? copy.saving : label ? copy.selectedSaved : copy.unlabelled}</small></div>
                <div className="spot-weld-annotation__label-head-actions">
                  {selectedRun?.target_schema?.dtype && <Tag color="blue">{copy.type}: {selectedRun.target_schema.dtype}</Tag>}
                  <button type="button" className="ant-btn" aria-label={copy.edit} onClick={() => setEditingLabelList((current) => !current)} disabled={!canLabel || savingLabel}>{editingLabelList ? copy.done : copy.edit}</button>
                </div>
              </div>
              <div className="spot-weld-annotation__label-options" role="group" aria-label={copy.labelOptions} style={labelOptionsStyle}>
                {labelOptions.map(([value, text]) => <span className="spot-weld-annotation__label-item" key={value}>
                  <button type="button" className={`spot-weld-annotation__label-option ${label === value ? "is-selected" : ""}`} aria-pressed={label === value} onClick={() => void saveLabel(value)} disabled={!canLabel || savingLabel}>{text}</button>
                  {editingLabelList && <button type="button" className="ant-btn ant-btn-icon-only ant-btn-danger-icon spot-weld-annotation__label-remove" aria-label={lang === "zh" ? `删除人工标签 ${text}` : `${copy.deleteCondition} ${text}`} onClick={() => removeLabelOption(value, text)} disabled={!canLabel || savingLabel}><DeleteOutlined /></button>}
                </span>)}
              </div>
              {editingLabelList && <div className="spot-weld-annotation__label-list-editor">
                <input aria-label={copy.newLabel} value={newLabelText} onChange={(event) => setNewLabelText(event.target.value)} placeholder={copy.inputNewLabel} onKeyDown={(event) => { if (event.key === "Enter") addLabelOption(); }} />
                <button type="button" className="ant-btn" onClick={addLabelOption} disabled={!canLabel || savingLabel || !newLabelText.trim()}>{copy.addLabel}</button>
              </div>}
              <div className="spot-weld-annotation__label-footer"><small className="spot-weld-annotation__status">{copy.status}: {selected.review_status || copy.pendingReview}</small><small>{copy.overrideHint}</small></div>
            </section>
            <section className="spot-weld-annotation__raw-data" aria-labelledby="spot-weld-raw-data-title">
              <div className="spot-weld-annotation__subhead"><h4 id="spot-weld-raw-data-title">{copy.sampleData}</h4><small>{copy.fieldsCount.replace("{count}", String(Object.keys(selected.table_values || {}).length))}</small></div>
              <div className="spot-weld-annotation__raw-data-list">
                {Object.entries(selected.table_values || {}).map(([name, value]) => {
                  return <div className="spot-weld-annotation__raw-data-row" key={name}><span>{name}</span><strong>{fullSampleValue(value)}</strong></div>;
                })}
                <div className="spot-weld-annotation__raw-data-row"><span>{copy.label}</span><strong>{label ? qualityLabelText(label) : copy.unlabelled}</strong></div>
              </div>
            </section>
          </>}
        </section>
      </div>
    </>
  );

  return (
    <AppLayout>
      <div className="page-shell fade-in spot-weld-annotation">
        {isTaskList ? (loadingProjects ? <div className="data-annotation__loading"><Spin /></div> : tasksView) : isSetup ? (loadingProjects || loadingDatasets ? <div className="data-annotation__loading"><Spin /></div> : setupView) : workspaceView}
      </div>
    </AppLayout>
  );
}
