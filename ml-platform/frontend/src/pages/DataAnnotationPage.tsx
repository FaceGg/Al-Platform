import { useEffect, useMemo, useRef, useState } from "react";
import { App as AntApp, Dropdown, Empty, Spin, Tag, Tooltip } from "antd";
import { DeleteOutlined, DownloadOutlined, ReloadOutlined, UploadOutlined } from "@ant-design/icons";
import { useNavigate, useSearchParams } from "react-router-dom";

import AppLayout from "../components/AppLayout";
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
  type QualityClusterPreview,
  type QualityRuleConfig,
  type QualitySample,
  type QualitySampleDetail,
  uploadQualityDataset,
  updateQualityRunRules,
  validateQualityDataset,
} from "../api/spotWeldQuality";
import { useI18n } from "../i18n";

interface ProjectOption { id: string; name: string; project_role?: string; }

interface DatasetOption {
  id?: string;
  artifact_id?: string;
  name?: string;
  format?: string;
  row_count?: number;
}

const LABEL_OPTIONS = [
  ["normal", "正常"],
  ["strong_splatter", "强飞溅缺陷"],
  ["weak_splatter", "弱飞溅缺陷"],
  ["spot_too_small", "焊点过小/虚焊"],
  ["spot_too_large", "焊点过大/烧穿"],
  ["energy_anomaly", "能量异常"],
  ["current_jump", "电流波形异常"],
  ["power_fluctuation", "功率波动异常"],
  ["anomaly_cluster", "飞溅倾向簇"],
] as const;

type LabelOption = readonly [string, string];
type CreatedTargetColumnDtype = "int" | "float" | "string";

const CREATED_TARGET_COLUMN_DTYPE_OPTIONS: ReadonlyArray<readonly [CreatedTargetColumnDtype, string]> = [
  ["int", "整数（int）"],
  ["float", "浮点数（float）"],
  ["string", "文本（string）"],
];

const LABEL_TEXT: Record<string, string> = Object.fromEntries(LABEL_OPTIONS);

const RULE_TEXT: Record<string, string> = {
  strong_splatter: "wld_spatter_strength >= 3",
  weak_splatter: "wld_spatter_strength = 2",
  spot_too_small: "0 < spotdiameter < 2 mm",
  spot_too_large: "spotdiameter > 80 mm",
  energy_anomaly: "|energy_dev| > 2.5σ",
  current_jump: "current_max_diff > P95",
  power_fluctuation: "power_std > P95",
  anomaly_cluster: "cluster=1 且 飞溅等级 >= 2",
  normal: "以上规则均不满足",
};

const DEFAULT_RULE_CONFIG: QualityRuleConfig = {
  strong_splatter_min: 3,
  weak_splatter_value: 2,
  spotdiameter_small_min: 0,
  spotdiameter_small_max: 2,
  spotdiameter_large_min: 80,
  energy_dev_sigma: 2.5,
  current_max_diff_percentile: 95,
  power_std_percentile: 95,
  spatter_cluster_id: 1,
  spatter_cluster_min_strength: 2,
};

const RULE_CONFIG_FIELDS: Array<{ key: keyof QualityRuleConfig; label: string; suffix: string }> = [
  { key: "strong_splatter_min", label: "强飞溅阈值", suffix: "级" },
  { key: "weak_splatter_value", label: "弱飞溅等级", suffix: "级" },
  { key: "spotdiameter_small_min", label: "虚焊直径下限", suffix: "mm" },
  { key: "spotdiameter_small_max", label: "虚焊直径上限", suffix: "mm" },
  { key: "spotdiameter_large_min", label: "烧穿直径阈值", suffix: "mm" },
  { key: "energy_dev_sigma", label: "能量偏差标准差", suffix: "σ" },
  { key: "current_max_diff_percentile", label: "电流跳变分位数", suffix: "P" },
  { key: "power_std_percentile", label: "功率波动分位数", suffix: "P" },
  { key: "spatter_cluster_id", label: "飞溅倾向簇编号", suffix: "" },
  { key: "spatter_cluster_min_strength", label: "簇内飞溅等级", suffix: "级" },
];

function qualityLabelText(value: string | null | undefined): string {
  if (!value) return "-";
  return LABEL_TEXT[value] || value;
}

function labelOptionsForRun(run: QualityRun | undefined): LabelOption[] {
  if (run?.label_mode !== "manual") return [...LABEL_OPTIONS];
  const classes = run.target_schema?.classes || [];
  return classes.length ? classes.map((value) => [value, value] as const) : [...LABEL_OPTIONS];
}

function labelHeadingForRun(run: QualityRun | undefined): string {
  if (run?.label_mode !== "manual" || !run.target_schema?.name || !run.target_schema?.dtype) return "人工标签";
  return `人工标签（${run.target_schema.name} · ${run.target_schema.dtype}）`;
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

function runModeText(run: QualityRun): string {
  return run.label_mode === "manual" ? "手动标注" : "自动标注";
}

const warningColor: Record<string, string> = {
  critical: "red", warning: "orange", notice: "gold", none: "green",
};

const WAVEFORM_FIELD_CHANNELS: Record<string, keyof NonNullable<QualitySampleDetail["waveforms"]>> = {
  cvei: "current",
  cvev: "voltage",
  cver: "resistance",
  cvep: "power",
};

function fullSampleValue(name: string, value: unknown, waveforms: QualitySampleDetail["waveforms"]): string {
  const channel = WAVEFORM_FIELD_CHANNELS[name];
  const displayValue = channel ? waveforms?.[channel] : value;
  if (typeof displayValue === "string") return displayValue;
  if (displayValue == null) return "-";
  if (Array.isArray(displayValue)) return `[${displayValue.map((item) => String(item)).join(", ")}]`;
  if (typeof displayValue === "object") return JSON.stringify(displayValue);
  return String(displayValue);
}

function sampleRuleState(
  name: string,
  detail: QualitySampleDetail,
  run: QualityRun | undefined,
): "matched" | "unmatched" | null {
  const source = detail.table_values || {};
  const featureValues = detail.feature_values || {};
  const rules = run?.rule_config || DEFAULT_RULE_CONFIG;
  const numeric = Number(source[name]);
  if (name === "wld_spatter_strength") {
    return numeric >= Number(rules.strong_splatter_min ?? 3) || numeric === Number(rules.weak_splatter_value ?? 2)
      ? "matched" : "unmatched";
  }
  if (name === "spotdiameter") {
    return (numeric > Number(rules.spotdiameter_small_min ?? 0) && numeric < Number(rules.spotdiameter_small_max ?? 2))
      || numeric > Number(rules.spotdiameter_large_min ?? 80) ? "matched" : "unmatched";
  }
  if (name === "energy") {
    return Math.abs(Number(featureValues.energy_dev)) > Number(rules.energy_dev_sigma ?? 2.5) ? "matched" : "unmatched";
  }
  if (name === "energy_dev") {
    return Math.abs(Number(source[name] ?? featureValues.energy_dev)) > Number(rules.energy_dev_sigma ?? 2.5) ? "matched" : "unmatched";
  }
  if (name === "cvei" || name === "current_max_diff") {
    return (detail.rule_hits || []).some((rule) => rule.code === "current_jump") ? "matched" : "unmatched";
  }
  if (name === "cvep" || name === "power_std") {
    return (detail.rule_hits || []).some((rule) => rule.code === "power_fluctuation") ? "matched" : "unmatched";
  }
  return null;
}

export default function DataAnnotationPage() {
  const { t } = useI18n();
  const { message } = AntApp.useApp();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const labels = (t.spotWeld || {}) as Record<string, string>;
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
  const [labelOptions, setLabelOptions] = useState<LabelOption[]>([...LABEL_OPTIONS]);
  const [editingLabelList, setEditingLabelList] = useState(false);
  const [newLabelText, setNewLabelText] = useState("");
  const [savingLabel, setSavingLabel] = useState(false);
  const [preparingRun, setPreparingRun] = useState(false);
  const [deletingRunId, setDeletingRunId] = useState("");
  const [savingRules, setSavingRules] = useState(false);
  const [labelMode, setLabelMode] = useState<QualityLabelMode>(searchParams.get("mode") === "manual" ? "manual" : "automatic");
  const [datasetColumns, setDatasetColumns] = useState<Array<{ name: string; dtype: string }>>([]);
  const [targetColumnMode, setTargetColumnMode] = useState<"existing" | "new">("existing");
  const [targetColumn, setTargetColumn] = useState("");
  const [targetColumnDtype, setTargetColumnDtype] = useState<CreatedTargetColumnDtype>("int");
  const [qualityModels, setQualityModels] = useState<QualityModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [weakSupervision, setWeakSupervision] = useState(false);
  const [clusterPreview, setClusterPreview] = useState<QualityClusterPreview | null>(null);
  const [clusterLabels, setClusterLabels] = useState<Record<string, string>>({});
  const [previewingClusters, setPreviewingClusters] = useState(false);
  const [ruleConfig, setRuleConfig] = useState<QualityRuleConfig>({ ...DEFAULT_RULE_CONFIG });
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
  const selectedRun = runs.find((item) => item.id === runId);
  const isSpotWeldFlow = true;
  const requestedView = searchParams.get("view");
  const requestedRunId = searchParams.get("runId");
  const isWorkspace = isSpotWeldFlow && (workspaceMode || requestedView === "workspace");
  const isTaskList = isSpotWeldFlow && !isWorkspace && (
    requestedView === "tasks"
    || (!searchParams.get("datasetId") && !searchParams.get("runId") && !requestedView)
  );
  const isSetup = isSpotWeldFlow && !isWorkspace && !isTaskList;
  const projectRole = selectedProject?.project_role || "";
  const canCreate = ["owner", "editor"].includes(projectRole);
  const canLabel = ["owner", "editor", "operator"].includes(projectRole);
  const canReview = ["owner", "editor"].includes(projectRole);
  const clusterMappingValues = Object.values(clusterLabels).map((value) => value.trim()).filter(Boolean);
  const clusterMappingComplete = Boolean(
    clusterPreview
    && clusterMappingValues.length >= clusterPreview.best_k
    && new Set(clusterMappingValues).size === clusterMappingValues.length,
  );

  useEffect(() => {
    if (!selectedRun) return;
    setRuleConfig({ ...DEFAULT_RULE_CONFIG, ...(selectedRun.rule_config || {}) });
  }, [selectedRun?.id, selectedRun?.rule_config]);

  useEffect(() => {
    setLabelOptions(labelOptionsForRun(selectedRun));
    setEditingLabelList(false);
    setNewLabelText("");
  }, [selectedRun?.id, selectedRun?.label_mode, selectedRun?.target_schema]);

  useEffect(() => {
    setLabelMode(searchParams.get("mode") === "manual" ? "manual" : "automatic");
  }, [searchParams]);

  useEffect(() => {
    if (!isSetup || !projectId || !datasetArtifactId) {
      setDatasetColumns([]);
      setTargetColumn("");
      return;
    }
    let active = true;
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
      .catch((error) => { if (active) message.error(formatApiError(error, "数据列加载失败")); });
    return () => { active = false; };
  }, [isSetup, projectId, datasetArtifactId, targetColumnMode, message]);

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
    setClusterLabels({});
  }, [datasetArtifactId, selectedModelId, weakSupervision]);

  useEffect(() => {
    let active = true;
    apiClient.get("/projects")
      .then((response) => {
        if (!active) return;
        const items = (response.data.items || response.data || []) as ProjectOption[];
        setProjects(items);
        setProjectId((current) => (
          items.some((item) => item.id === current) ? current : items[0]?.id || ""
        ));
      })
      .catch(() => { if (active) setProjects([]); })
      .finally(() => { if (active) setLoadingProjects(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!isSpotWeldFlow || loadingProjects || !projects.some((project) => project.id === projectId)) {
      runsRequestId.current += 1;
      setRuns([]);
      if (!isSpotWeldFlow) setRunId("");
      return;
    }
    if (!projectId) { runsRequestId.current += 1; setRuns([]); setRunId(""); return; }
    let active = true;
    const expectedProjectId = projectId;
    const requestId = ++runsRequestId.current;
    setLoadingRuns(true);
    listQualityRuns(projectId)
      .then((items) => {
        if (!active || runsRequestId.current !== requestId || activeContextRef.current.projectId !== expectedProjectId) return;
        setRuns(items);
        setRunId((current) => {
          if (items.some((run) => run.id === current)) return current;
          return requestedRunId && items.some((run) => run.id === requestedRunId) ? requestedRunId : "";
        });
      })
      .catch((error) => {
        if (active && runsRequestId.current === requestId && activeContextRef.current.projectId === expectedProjectId) {
          message.error(formatApiError(error, "质量运行加载失败"));
        }
      })
      .finally(() => {
        if (active && runsRequestId.current === requestId && activeContextRef.current.projectId === expectedProjectId) {
          setLoadingRuns(false);
        }
      });
    return () => { active = false; };
  }, [isSpotWeldFlow, loadingProjects, projects, projectId, message, requestedRunId]);

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
    setSearchParams((current) => {
      if (projectId) current.set("projectId", projectId); else current.delete("projectId");
      if (datasetArtifactId) current.set("datasetId", datasetArtifactId); else current.delete("datasetId");
      if (runId) current.set("runId", runId); else current.delete("runId");
      return current;
    }, { replace: true });
  }, [projectId, datasetArtifactId, runId, setSearchParams]);

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

  const startQualityRun = async (
    nextDatasetArtifactId: string,
    nextLabelMode: QualityLabelMode = labelMode,
    nextRuleConfig: QualityRuleConfig = ruleConfig,
  ) => {
    const normalizedTargetColumn = targetColumn.trim();
    if (!projectId || !normalizedTargetColumn) return;
    const targetColumnCreated = targetColumnMode === "new";
    const inputColumns = datasetColumns
      .map((item) => item.name)
      .filter((name) => name !== normalizedTargetColumn);
    const validation = await validateQualityDataset(projectId, nextDatasetArtifactId, {}, {
      label_mode: nextLabelMode,
      rule_config: nextLabelMode === "automatic" ? nextRuleConfig : {},
      algorithm_ids: [],
      search_method: "bayesian",
      max_trials: 20,
      time_budget: 600,
      target_column: normalizedTargetColumn,
      target_column_created: targetColumnCreated,
      target_column_dtype: targetColumnCreated ? targetColumnDtype : undefined,
      input_columns: inputColumns,
    });
    if (!validation.valid_rows || validation.errors.length) {
      const firstError = validation.errors[0];
      message.error(firstError?.code || "报告字段或波形校验失败");
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
      target_column: normalizedTargetColumn,
      target_column_created: targetColumnCreated,
      ...(targetColumnCreated ? { target_column_dtype: targetColumnDtype } : {}),
      input_columns: inputColumns,
    };
    if (nextLabelMode === "automatic") {
      payload.rule_config = nextRuleConfig;
      payload.selected_model_id = selectedModelId;
      payload.weak_supervision = weakSupervision;
      payload.cluster_labels = weakSupervision ? clusterLabels : {};
      payload.process_rules = weakSupervision ? RULE_CONFIG_FIELDS.map((field) => ({
        key: field.key,
        name: field.label,
        value: nextRuleConfig[field.key],
        unit: field.suffix,
      })) : [];
    }
    const run = await createQualityRun(projectId, payload);
    setWorkspaceMode(true);
    setSearchParams((current) => {
      current.set("type", "spot-weld");
      current.set("view", "workspace");
      current.set("projectId", projectId);
      current.set("datasetId", nextDatasetArtifactId);
      current.set("runId", run.id);
      current.set("mode", nextLabelMode);
      return current;
    }, { replace: true });
    setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
    setRunId(run.id);
    setDatasetArtifactId(nextDatasetArtifactId);
    setSamples([]);
    setSelected(null);
    message.success(`${nextLabelMode === "automatic" ? "自动标注" : "手动标注"}已创建 ${validation.valid_rows} 条记录的质量运行`);
  };

  const handleReportUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !projectId || !canCreate) return;
    const extension = file.name.split(".").pop()?.toLowerCase();
    if (!extension || !["csv", "xls", "xlsx"].includes(extension)) {
      message.error("仅支持 CSV、XLS 或 XLSX 报告");
      return;
    }
    setPreparingRun(true);
    try {
      const artifact = await uploadQualityDataset(projectId, file);
      setDatasetArtifactId(artifact.artifact_id);
      setWorkspaceMode(false);
      setSearchParams((current) => {
        current.set("type", "spot-weld");
        current.set("projectId", projectId);
        current.set("datasetId", artifact.artifact_id);
        current.delete("runId");
        current.set("mode", labelMode);
        return current;
      }, { replace: true });
      message.success("报告已上传，请选择标注方式后开始");
    } catch (error) {
      message.error(formatApiError(error, "报告上传或质量运行创建失败"));
    } finally {
      setPreparingRun(false);
    }
  };

  const handleSelectedDataset = async () => {
    if (!datasetArtifactId || !canCreate) return;
    setPreparingRun(true);
    try {
      await startQualityRun(datasetArtifactId, labelMode, ruleConfig);
    } catch (error) {
      message.error(formatApiError(error, "质量运行创建失败"));
    } finally {
      setPreparingRun(false);
    }
  };

  const openSetup = (nextMode: QualityLabelMode = "automatic") => {
    setWorkspaceMode(false);
    setRunId("");
    setLabelMode(nextMode);
    setSearchParams((current) => {
      current.set("type", "spot-weld");
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
    next.set("type", "spot-weld");
    next.set("view", "tasks");
    if (projectId) next.set("projectId", projectId);
    next.set("mode", labelMode);
    setSearchParams(next, { replace: true });
  };

  const openRunWorkspace = (run: QualityRun, mode: QualityLabelMode = run.label_mode || "automatic") => {
    setWorkspaceMode(true);
    setRunId(run.id);
    setLabelMode(mode);
    setSearchParams((current) => {
      current.set("type", "spot-weld");
      current.set("view", "workspace");
      current.set("projectId", projectId);
      current.set("runId", run.id);
      current.set("mode", mode);
      return current;
    }, { replace: true });
  };

  const updateRuleConfig = (key: keyof QualityRuleConfig, value: string) => {
    const numeric = Number(value);
    setRuleConfig((current) => ({ ...current, [key]: Number.isFinite(numeric) ? numeric : 0 }));
  };

  const resetRuleConfig = () => setRuleConfig({ ...DEFAULT_RULE_CONFIG });

  const refreshRuns = async () => {
    if (!projectId) return;
    const expectedProjectId = projectId;
    const requestId = ++runsRequestId.current;
    setLoadingRuns(true);
    try {
      const items = await listQualityRuns(expectedProjectId);
      if (runsRequestId.current !== requestId || activeContextRef.current.projectId !== expectedProjectId) return;
      setRuns(items);
    } catch (error) {
      if (runsRequestId.current === requestId && activeContextRef.current.projectId === expectedProjectId) {
        message.error(formatApiError(error, "质量运行加载失败"));
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

  const previewClusters = async () => {
    if (!projectId || !datasetArtifactId || !selectedModelId || previewingClusters) return;
    setPreviewingClusters(true);
    try {
      const preview = await previewQualityClusters(projectId, {
        dataset_artifact_id: datasetArtifactId,
        selected_model_id: selectedModelId,
      });
      setClusterPreview(preview);
      setClusterLabels(Object.fromEntries(
        Object.keys(preview.cluster_counts).map((clusterId) => [clusterId, ""]),
      ));
      message.success(`聚类完成，最优 K=${preview.best_k}`);
    } catch (error) {
      message.error(formatApiError(error, "聚类预览失败"));
    } finally {
      setPreviewingClusters(false);
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
    if (!projectId || deletingRunId || !window.confirm(`确认删除标注任务 ${run.id}？`)) return;
    setDeletingRunId(run.id);
    try {
      await deleteQualityRun(projectId, run.id);
      setRuns((current) => current.filter((item) => item.id !== run.id));
      message.success("标注任务已删除");
    } catch (error) {
      message.error(formatApiError(error, "标注任务删除失败"));
    } finally {
      setDeletingRunId("");
    }
  };

  const saveRuleConfiguration = async () => {
    if (!projectId || !runId || !selectedRun || savingRules) return;
    setSavingRules(true);
    try {
      const updated = await updateQualityRunRules(projectId, runId, ruleConfig);
      setRuns((current) => current.map((item) => item.id === updated.id ? updated : item));
      await refreshActiveWorkspace();
      message.success(selectedRun.label_mode === "manual" ? "标注规则已保存" : "规则已保存，自动标签已重新计算");
    } catch (error) {
      message.error(formatApiError(error, "标注规则保存失败"));
    } finally {
      setSavingRules(false);
    }
  };

  const submitRunForReview = async () => {
    if (!projectId || !runId || !canLabel) return;
    try {
      const response = await apiClient.post(`/projects/${projectId}/spot-weld/runs/${runId}/submit-review`);
      message.success(`已提交 ${response.data?.submitted_count ?? 0} 条标注复核`);
      await refreshSamples(selected?.id || "");
    } catch (error) {
      message.error(formatApiError(error, "提交复核失败"));
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
      anchor.download = `spot-weld-annotations-${runId.slice(0, 8)}.${format}`;
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

  const tasksView = (
    <>
      <div className="page-header data-annotation__tasks-header">
        <div className="page-header-copy">
          <h2 className="page-title">标注任务</h2>
        </div>
        <div className="data-annotation__task-actions">
          <button type="button" className="ant-btn" onClick={() => openSetup("manual")}>新建手动标注任务</button>
          <button type="button" className="ant-btn ant-btn-primary" onClick={() => openSetup("automatic")}>新建自动标注任务</button>
        </div>
      </div>
      <div className="table-surface data-annotation__tasks-surface">
      <section className="data-annotation__tasks" aria-label="点焊标注任务列表">
        {loadingRuns ? <Spin /> : runs.length === 0 ? <Empty description="暂无点焊标注任务" /> : runs.map((run) => (
          <article className="data-annotation__task" key={run.id}>
            <div className="data-annotation__task-main">
              <strong>{run.id.slice(0, 8)}</strong>
              <span>{runModeText(run)}</span>
              <Tag color={run.status === "completed" ? "green" : run.status === "failed" ? "red" : "blue"}>{run.status}</Tag>
            </div>
            <div className="data-annotation__task-progress" aria-label={`标注进度 ${run.id}`}>
              <span>标注进度</span><strong>{annotationProgressText(run)}</strong>
            </div>
              <div className="data-annotation__task-buttons">
              <button
                type="button"
                className="ant-btn"
                aria-label={`${run.label_mode === "manual" ? "手工标注" : "查看标注"} ${run.id}`}
                onClick={() => openRunWorkspace(run)}
              >
                {run.label_mode === "manual" ? "手工标注" : "查看标注"}
              </button>
              <Tooltip title={["completed", "failed", "cancelled"].includes(String(run.status)) ? "删除标注任务" : "运行中的任务不能删除"}>
                <button type="button" className="ant-btn ant-btn-icon-only" aria-label={`删除标注任务 ${run.id}`} onClick={() => void removeRun(run)} disabled={deletingRunId === run.id || !["completed", "failed", "cancelled"].includes(String(run.status))}><DeleteOutlined /></button>
              </Tooltip>
            </div>
          </article>
        ))}
      </section>
      </div>
    </>
  );

  const setupView = (
    <>
      <div className="page-header spot-weld-annotation__workspace-header">
        <div className="page-header-copy">
          <h2 className="page-title">{labelMode === "manual" ? "新建手动标注任务" : "新建自动标注任务"}</h2>
          <p className="page-subtitle">选择数据文件和必填目标列后创建任务</p>
        </div>
        <button type="button" className="ant-btn" onClick={returnToTaskList}>返回任务列表</button>
      </div>
      <section className="data-annotation__setup" aria-label="点焊标注配置">
        <div className="data-annotation__setup-grid">
          <div className="data-annotation__setup-field">
            <label htmlFor="spot-weld-setup-project">项目</label>
            <select id="spot-weld-setup-project" aria-label="Project" value={projectId} onChange={(event) => { setProjectId(event.target.value); setDatasetArtifactId(""); setRunId(""); }} disabled={loadingProjects}>
              <option value="">选择项目</option>
              {projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
            </select>
          </div>
          <div className="data-annotation__setup-field">
            <label htmlFor="spot-weld-dataset">数据管理文件</label>
            <select
              id="spot-weld-dataset"
              aria-label="数据管理文件"
              value={datasetArtifactId}
              onChange={(event) => {
                const next = event.target.value;
                setDatasetArtifactId(next);
                setSearchParams((current) => { if (next) current.set("datasetId", next); else current.delete("datasetId"); current.delete("runId"); return current; }, { replace: true });
              }}
              disabled={!projectId || loadingDatasets}
            >
              <option value="">选择兼容文件</option>
              {datasets.map((dataset) => {
                const artifactId = dataset.artifact_id || dataset.id || "";
                return <option value={artifactId} key={artifactId}>{dataset.name || artifactId} · {dataset.row_count ?? 0} 行</option>;
              })}
            </select>
          </div>
        </div>
        <div className="data-annotation__source-actions">
          <input ref={uploadInputRef} className="spot-weld-annotation__sr-only" type="file" accept=".csv,.xls,.xlsx" aria-label="上传点焊报告" onChange={handleReportUpload} />
          <button type="button" className="ant-btn" onClick={() => uploadInputRef.current?.click()} disabled={!canCreate || preparingRun}><UploadOutlined />上传 CSV / XLS / XLSX</button>
        </div>
        <div className="data-annotation__setup-grid">
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
        </div>
        {labelMode === "automatic" && <div className="data-annotation__setup-grid">
          <div className="data-annotation__setup-field">
            <label htmlFor="quality-registered-model">选择模型</label>
            <select id="quality-registered-model" aria-label="选择模型" value={selectedModelId} onChange={(event) => setSelectedModelId(event.target.value)}>
              <option value="">选择当前项目已注册模型</option>
              {qualityModels.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.version || "v1"} · {model.framework || "-"}</option>)}
            </select>
          </div>
          <label className="data-annotation__setup-field" htmlFor="quality-weak-supervision">
            <span>弱监督标注策略</span>
            <input id="quality-weak-supervision" aria-label="弱监督标注策略" type="checkbox" checked={weakSupervision} onChange={(event) => setWeakSupervision(event.target.checked)} />
          </label>
          {weakSupervision && <button type="button" className="ant-btn" onClick={() => void previewClusters()} disabled={!datasetArtifactId || !selectedModelId || previewingClusters}>
            {previewingClusters ? "聚类中..." : "预览聚类结果"}
          </button>}
        </div>}
        {labelMode === "automatic" && weakSupervision && <section className="data-annotation__rules" aria-labelledby="quality-rule-title">
          <div className="data-annotation__rules-head">
            <div><h3 id="quality-rule-title">工艺规则</h3><p>工艺规则用于弱监督标注证据，开始任务后仅展示快照。</p></div>
            <div className="data-annotation__rule-actions">
              <button type="button" className="ant-btn" onClick={resetRuleConfig} disabled={!canCreate}>点焊工艺规则模版</button>
              <button type="button" className="ant-btn" onClick={resetRuleConfig} disabled={!canCreate}>恢复默认规则</button>
            </div>
          </div>
          <div className="data-annotation__rule-table">
            {RULE_CONFIG_FIELDS.map((field) => (
              <label key={field.key} htmlFor={`quality-rule-${field.key}`}>
                <span>{field.label}</span>
                <div><input id={`quality-rule-${field.key}`} aria-label={field.label} type="number" step="any" value={ruleConfig[field.key]} onChange={(event) => updateRuleConfig(field.key, event.target.value)} disabled={!canCreate} /><small>{field.suffix}</small></div>
              </label>
            ))}
          </div>
          <div className="data-annotation__rule-reference">
            {LABEL_OPTIONS.filter(([value]) => value !== "normal").map(([value, text]) => <span key={value}><Tag>{text}</Tag><small>{RULE_TEXT[value]}</small></span>)}
            <span><Tag color="green">正常</Tag><small>{RULE_TEXT.normal}</small></span>
          </div>
        </section>}
        {labelMode === "automatic" && weakSupervision && clusterPreview && <section className="data-annotation__rules" aria-labelledby="quality-cluster-title">
          <div className="data-annotation__rules-head"><div><h3 id="quality-cluster-title">聚类结果</h3><p>按轮廓系数选择的最优 K：{clusterPreview.best_k}</p></div></div>
          <div className="data-annotation__rule-table">
            {Object.entries(clusterPreview.cluster_counts).map(([clusterId, count]) => <label key={clusterId} htmlFor={`quality-cluster-label-${clusterId}`}>
              <span>簇 {clusterId}（{count} 条）</span>
              <input id={`quality-cluster-label-${clusterId}`} aria-label={`簇 ${clusterId} 标签`} value={clusterLabels[clusterId] || ""} onChange={(event) => setClusterLabels((current) => ({ ...current, [clusterId]: event.target.value }))} placeholder="输入单标签" />
            </label>)}
          </div>
        </section>}
        <div className="data-annotation__setup-footer">
          <button type="button" className="ant-btn ant-btn-primary" onClick={() => void handleSelectedDataset()} disabled={!canCreate || !projectId || !datasetArtifactId || !targetColumn.trim() || (labelMode === "automatic" && !selectedModelId) || (labelMode === "automatic" && weakSupervision && !clusterMappingComplete) || preparingRun}>
            {preparingRun ? "准备中..." : labelMode === "automatic" ? "开始自动标注" : "开始手动标注"}
          </button>
        </div>
      </section>
    </>
  );

  const workspaceView = (
    <>
      <div className="page-header">
        <div className="page-header-copy">
          <p className="page-kicker">QUALITY / LABELING</p>
          <h2 className="page-title">{labels.title || "数据标注"}</h2>
          <p className="page-subtitle">{selectedProject?.name || "点焊样本逐条标注"}</p>
        </div>
        <div className="spot-weld-annotation__controls">
          <label htmlFor="spot-weld-annotation-project">Project</label>
          <select id="spot-weld-annotation-project" className="spot-weld-annotation__project" aria-label="Project" value={projectId} onChange={(event) => { setProjectId(event.target.value); setRunId(""); }} disabled={loadingProjects}>
            <option value="">选择项目</option>
            {projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
          </select>
        </div>
        <div className="spot-weld-annotation__actions">
          <button type="button" className="ant-btn" aria-label="返回任务列表" onClick={returnToTaskList}>返回任务列表</button>
          {projectId && selectedRun && <Dropdown trigger={["click"]} disabled={downloadingAnnotationExport} menu={{ items: [{ key: "csv", label: "CSV" }, { key: "xlsx", label: "XLSX" }], onClick: ({ key }) => { void downloadAnnotations(key as "csv" | "xlsx"); } }}>
            <button type="button" className="ant-btn" aria-label="导出标注" disabled={downloadingAnnotationExport}><DownloadOutlined />导出标注</button>
          </Dropdown>}
          {projectId && selectedRun?.status === "completed" && <button type="button" className="ant-btn" aria-label="保存到数据管理" onClick={() => void saveToDataManagement()} disabled={!canLabel || savingLabeledDataset}>{savingLabeledDataset ? "保存中..." : "保存到数据管理"}</button>}
          <Tooltip title="刷新标注任务"><button type="button" className="ant-btn ant-btn-icon-only" aria-label="刷新标注任务" onClick={() => { void refreshRuns(); }} disabled={!projectId || loadingRuns}><ReloadOutlined /></button></Tooltip>
        </div>
      </div>
      <div className="spot-weld-annotation__workspace spot-weld-annotation__workspace--detail">
        <section className="spot-weld-annotation__region spot-weld-annotation__queue" aria-labelledby="spot-weld-queue-title">
          <div className="spot-weld-annotation__region-head"><h3 id="spot-weld-queue-title">{labels.queue || "样本队列"}</h3><div className="spot-weld-annotation__queue-meta"><Tag>{samples.length} 条</Tag>{selectedRun && <Tag color="blue">{annotationProgressText(selectedRun)}</Tag>}</div></div>
          {loadingRuns || loadingSamples ? <Spin /> : samples.length === 0 ? <Empty description="暂无样本" /> : (
            <div className="spot-weld-annotation__sample-list">
              {samples.map((sample) => <button type="button" className={`spot-weld-annotation__sample ${selected?.id === sample.id ? "is-selected" : ""}`} key={sample.id} onClick={() => selectSample(sample)} aria-label={sample.display_id}>
                <span><strong>{sample.display_id}</strong><small>第 {sample.source_row_index ?? "-"} 行</small></span>
                <Tag color={warningColor[sample.warning_level || "none"]}>{qualityLabelText(sample.current_label || sample.automatic_label) || "未标注"}</Tag>
              </button>)}
            </div>
          )}
        </section>
        <section className="spot-weld-annotation__region spot-weld-annotation__detail" aria-labelledby="spot-weld-detail-title">
          <div className="spot-weld-annotation__region-head"><h3 id="spot-weld-detail-title">样本详情</h3>{selectedRun && <Tag color={selectedRun.status === "completed" ? "green" : "blue"}>{selectedRun.status}</Tag>}</div>
          {loadingDetail ? <Spin /> : !selected ? <Empty description="选择样本查看详情" /> : <>
            <section className="spot-weld-annotation__label-editor" aria-label="人工标签">
              <div className="spot-weld-annotation__label-head">
                <div className="spot-weld-annotation__subhead"><h4>{labelHeadingForRun(selectedRun)}</h4><small>{savingLabel ? "保存中..." : label ? "已选择并自动保存" : "未标注"}</small></div>
                <div className="spot-weld-annotation__label-head-actions">
                  {selectedRun?.target_schema?.dtype && <Tag color="blue">类型：{selectedRun.target_schema.dtype}</Tag>}
                  <button type="button" className="ant-btn" aria-label="编辑" onClick={() => setEditingLabelList((current) => !current)} disabled={!canLabel || savingLabel}>{editingLabelList ? "完成" : "编辑"}</button>
                </div>
              </div>
              <div className="spot-weld-annotation__label-options" role="group" aria-label="人工标签选项">
                {labelOptions.map(([value, text]) => <span className="spot-weld-annotation__label-item" key={value}>
                  <button type="button" className={`spot-weld-annotation__label-option ${label === value ? "is-selected" : ""}`} aria-pressed={label === value} onClick={() => void saveLabel(value)} disabled={!canLabel || savingLabel}>{text}</button>
                  {editingLabelList && <button type="button" className="ant-btn ant-btn-icon-only spot-weld-annotation__label-remove" aria-label={`删除人工标签 ${text}`} onClick={() => removeLabelOption(value, text)} disabled={!canLabel || savingLabel}><DeleteOutlined /></button>}
                </span>)}
              </div>
              {editingLabelList && <div className="spot-weld-annotation__label-list-editor">
                <input aria-label="新建人工标签" value={newLabelText} onChange={(event) => setNewLabelText(event.target.value)} placeholder="输入新标签名称" onKeyDown={(event) => { if (event.key === "Enter") addLabelOption(); }} />
                <button type="button" className="ant-btn" onClick={addLabelOption} disabled={!canLabel || savingLabel || !newLabelText.trim()}>添加标签</button>
              </div>}
              <div className="spot-weld-annotation__label-footer"><small className="spot-weld-annotation__status">当前状态：{selected.review_status || "pending_review"}</small><small>点击标签即可覆盖当前样本结果</small></div>
            </section>
            {selectedRun?.label_mode === "automatic" && <section className="spot-weld-annotation__annotation-rules" aria-labelledby="spot-weld-rule-list-title">
              <div className="spot-weld-annotation__subhead"><h4 id="spot-weld-rule-list-title">工艺规则</h4><small>任务创建时的规则快照，仅供查看</small></div>
              <div className="spot-weld-annotation__rule-list">
                {LABEL_OPTIONS.map(([value, text]) => <div className="spot-weld-annotation__rule-item" key={value}><Tag color={value === "normal" ? "green" : "blue"}>{text}</Tag><span>{RULE_TEXT[value]}</span></div>)}
              </div>
            </section>}
            <section className="spot-weld-annotation__raw-data" aria-labelledby="spot-weld-raw-data-title">
              <div className="spot-weld-annotation__subhead"><h4 id="spot-weld-raw-data-title">当前样本数据</h4><small>{Object.keys(selected.table_values || {}).length} 个真实字段</small></div>
              <div className="spot-weld-annotation__raw-data-list">
                {Object.entries(selected.table_values || {}).map(([name, value]) => {
                  return <div className="spot-weld-annotation__raw-data-row" key={name}><span>{name}</span><strong>{fullSampleValue(name, value, selected.waveforms)}</strong></div>;
                })}
                <div className="spot-weld-annotation__raw-data-row"><span>label</span><strong>{label ? qualityLabelText(label) : "未标注"}</strong></div>
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
