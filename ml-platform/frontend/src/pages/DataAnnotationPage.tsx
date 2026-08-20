import { useEffect, useMemo, useRef, useState } from "react";
import { App as AntApp, Dropdown, Empty, Spin, Tag, Tooltip } from "antd";
import { DeleteOutlined, DownloadOutlined, ExperimentOutlined, ReloadOutlined, UploadOutlined } from "@ant-design/icons";
import { useNavigate, useSearchParams } from "react-router-dom";

import AppLayout from "../components/AppLayout";
import { formatApiError, default as apiClient } from "../api/client";
import { listDatasets } from "../api/datasets";
import {
  createQualityDemoDataset,
  createQualityRun,
  deleteQualityRun,
  downloadQualityAnnotationExport,
  getQualitySample,
  getQualityRun,
  listQualityRuns,
  listQualitySamples,
  saveLabeledDataset,
  submitQualityLabel,
  type QualityRun,
  type QualityLabelMode,
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
  const [savingLabel, setSavingLabel] = useState(false);
  const [preparingRun, setPreparingRun] = useState(false);
  const [deletingRunId, setDeletingRunId] = useState("");
  const [savingRules, setSavingRules] = useState(false);
  const [labelMode, setLabelMode] = useState<QualityLabelMode>(searchParams.get("mode") === "manual" ? "manual" : "automatic");
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

  useEffect(() => {
    if (!selectedRun) return;
    setRuleConfig({ ...DEFAULT_RULE_CONFIG, ...(selectedRun.rule_config || {}) });
  }, [selectedRun?.id, selectedRun?.rule_config]);

  useEffect(() => {
    setLabelMode(searchParams.get("mode") === "manual" ? "manual" : "automatic");
  }, [searchParams]);

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
          const requestedRunId = searchParams.get("runId");
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
  }, [isSpotWeldFlow, loadingProjects, projects, projectId, message, searchParams]);

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
    if (!projectId) return;
    const validation = await validateQualityDataset(projectId, nextDatasetArtifactId, {}, {
      label_mode: nextLabelMode,
      rule_config: nextLabelMode === "automatic" ? nextRuleConfig : {},
      algorithm_ids: [],
      search_method: "bayesian",
      max_trials: 20,
      time_budget: 600,
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
    };
    if (nextLabelMode === "automatic") payload.rule_config = nextRuleConfig;
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

  const handleCreateDemo = async (rowCount: number) => {
    if (!projectId || !canCreate) return;
    setPreparingRun(true);
    try {
      const artifact = await createQualityDemoDataset(projectId, rowCount);
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
      message.success("模拟数据已准备，请选择标注方式后开始");
    } catch (error) {
      message.error(formatApiError(error, "模拟数据创建或质量运行启动失败"));
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
    const sampleId = selected.id;
    const previousLabel = label;
    setLabel(nextLabel);
    setSavingLabel(true);
    try {
      const saved = await submitQualityLabel(projectId, runId, sampleId, { label: nextLabel, note: "" });
      setSelected((current) => current?.id === sampleId ? { ...current, ...saved } : current);
      setSamples((current) => current.map((sample) => sample.id === sampleId ? { ...sample, ...saved } : sample));
      message.success("标签已保存");
    } catch (error) {
      setLabel(previousLabel);
      message.error(formatApiError(error, "标签保存失败"));
    } finally {
      setSavingLabel(false);
    }
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
    if (selectedSample) await selectSample(selectedSample);
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
      <section className="data-annotation__tasks" aria-label="点焊标注任务列表">
        <div className="data-annotation__task-actions">
          <button type="button" className="ant-btn" onClick={() => openSetup("manual")}>新建手动标注任务</button>
          <button type="button" className="ant-btn ant-btn-primary" onClick={() => openSetup("automatic")}>新建自动标注任务</button>
        </div>
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
              {["completed", "failed", "cancelled"].includes(String(run.status)) && <Tooltip title="删除标注任务">
                <button type="button" className="ant-btn ant-btn-icon-only" aria-label={`删除标注任务 ${run.id}`} onClick={() => void removeRun(run)} disabled={deletingRunId === run.id}><DeleteOutlined /></button>
              </Tooltip>}
            </div>
          </article>
        ))}
      </section>
    </>
  );

  const setupView = (
    <>
      <div className="page-header">
        <div className="page-header-copy">
          <p className="page-kicker">SPOT WELD / SETUP</p>
          <h2 className="page-title">点焊标注配置</h2>
          <p className="page-subtitle">先选择报告数据和标注方式，再进入样本队列复核</p>
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
          <Dropdown
            trigger={["click"]}
            disabled={!canCreate || preparingRun}
            menu={{
              items: [
                { key: "60", label: "快速样本（60 条）" },
                { key: "1875", label: "报告复现（1875 条）" },
              ],
              onClick: ({ key }) => { void handleCreateDemo(Number(key)); },
            }}
          >
            <button type="button" className="ant-btn" disabled={!canCreate || preparingRun}><ExperimentOutlined />准备模拟数据</button>
          </Dropdown>
        </div>
        <div className="data-annotation__mode-picker" role="group" aria-label="标注方式">
          <label className={labelMode === "automatic" ? "is-selected" : ""}>
            <input type="radio" name="quality-label-mode" value="automatic" aria-label="自动标注" checked={labelMode === "automatic"} onChange={() => { setLabelMode("automatic"); setSearchParams((current) => { current.set("mode", "automatic"); return current; }, { replace: true }); }} />
            <span>自动标注</span>
            <small>按可编辑规则生成初始标签</small>
          </label>
          <label className={labelMode === "manual" ? "is-selected" : ""}>
            <input type="radio" name="quality-label-mode" value="manual" aria-label="手动标注" checked={labelMode === "manual"} onChange={() => { setLabelMode("manual"); setSearchParams((current) => { current.set("mode", "manual"); return current; }, { replace: true }); }} />
            <span>手动标注</span>
            <small>只提取特征，逐条人工选择标签</small>
          </label>
        </div>
        {labelMode === "automatic" && <section className="data-annotation__rules" aria-labelledby="quality-rule-title">
          <div className="data-annotation__rules-head">
            <div><h3 id="quality-rule-title">自动标注规则</h3><p>修改后的阈值会随本次运行保存，并实际用于生成规则命中。</p></div>
            <button type="button" className="ant-btn" onClick={resetRuleConfig} disabled={!canCreate}>恢复默认规则</button>
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
        {labelMode === "manual" && <div className="data-annotation__manual-note">手动模式不会写入自动标签、规则命中、聚类结果或模型概率；完成特征提取后进入逐条人工标注。</div>}
        <div className="data-annotation__setup-footer">
          <div className="data-annotation__existing-run">
            <label htmlFor="spot-weld-existing-run">已有质量运行</label>
            <select id="spot-weld-existing-run" aria-label="已有质量运行" value={runId} onChange={(event) => {
              const nextRun = runs.find((run) => run.id === event.target.value);
              if (nextRun) openRunWorkspace(nextRun);
              else setRunId("");
            }} disabled={!projectId || loadingRuns}>
              <option value="">选择后继续复核</option>
              {runs.map((run) => <option value={run.id} key={run.id}>{run.id.slice(0, 8)} · {run.status}</option>)}
            </select>
          </div>
          <button type="button" className="ant-btn ant-btn-primary" onClick={() => void handleSelectedDataset()} disabled={!canCreate || !projectId || !datasetArtifactId || preparingRun}>
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
          <button type="button" className="ant-btn ant-btn-primary" aria-label="提交复核" onClick={() => void submitRunForReview()} disabled={!canLabel || !runId}>提交复核</button>
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
            <section className="spot-weld-annotation__annotation-rules" aria-labelledby="spot-weld-rule-list-title">
              <div className="spot-weld-annotation__subhead"><h4 id="spot-weld-rule-list-title">{selectedRun?.label_mode === "manual" ? "标注规则" : "自动标注规则"}</h4><small>{selectedRun?.label_mode === "manual" ? "仅作为人工判断参考" : "保存后重新计算全部自动标签"}</small></div>
              <div className="data-annotation__rule-table">
                {RULE_CONFIG_FIELDS.map((field) => <label key={field.key} htmlFor={`quality-detail-rule-${field.key}`}>
                  <span>{field.label}</span>
                  <div><input id={`quality-detail-rule-${field.key}`} aria-label={field.label} type="number" step="any" value={ruleConfig[field.key]} onChange={(event) => updateRuleConfig(field.key, event.target.value)} disabled={!canCreate || savingRules} /><small>{field.suffix}</small></div>
                </label>)}
              </div>
              <div className="spot-weld-annotation__rule-list">
                {LABEL_OPTIONS.map(([value, text]) => <div className="spot-weld-annotation__rule-item" key={value}><Tag color={value === "normal" ? "green" : "blue"}>{text}</Tag><span>{RULE_TEXT[value]}</span></div>)}
              </div>
              <button type="button" className="ant-btn ant-btn-primary" aria-label="保存标注规则" onClick={() => void saveRuleConfiguration()} disabled={!canCreate || savingRules}>{savingRules ? "保存中..." : "保存标注规则"}</button>
            </section>
            <section className="spot-weld-annotation__raw-data" aria-labelledby="spot-weld-raw-data-title">
              <div className="spot-weld-annotation__subhead"><h4 id="spot-weld-raw-data-title">当前样本数据</h4><small>{Object.keys(selected.table_values || {}).length} 个真实字段</small></div>
              <div className="spot-weld-annotation__raw-data-list">
                {Object.entries(selected.table_values || {}).map(([name, value]) => {
                  const state = sampleRuleState(name, selected, selectedRun);
                  return <div className={`spot-weld-annotation__raw-data-row ${state ? `is-${state}` : ""}`} key={name}><span>{name}</span><strong>{fullSampleValue(name, value, selected.waveforms)}</strong></div>;
                })}
                <div className={`spot-weld-annotation__raw-data-row ${label ? "is-label-selected" : ""}`}><span>label</span><strong>{label ? qualityLabelText(label) : "未标注"}</strong></div>
              </div>
            </section>
            <section className="spot-weld-annotation__label-editor" aria-label="人工标签">
              <div className="spot-weld-annotation__subhead"><h4>人工标签</h4><small>{savingLabel ? "保存中..." : label ? "已选择并自动保存" : "未选择标签"}</small></div>
              <div className="spot-weld-annotation__label-options">
                {LABEL_OPTIONS.map(([value, text]) => <button type="button" className={`spot-weld-annotation__label-option ${label === value ? "is-selected" : ""}`} aria-pressed={label === value} key={value} onClick={() => void saveLabel(value)} disabled={!canLabel || savingLabel}>{text}</button>)}
              </div>
              <small className="spot-weld-annotation__status">当前状态：{selected.review_status || "pending_review"}</small>
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
