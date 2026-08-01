import { useEffect, useMemo, useRef, useState } from "react";
import { App as AntApp, Dropdown, Empty, Spin, Tag, Tooltip } from "antd";
import { DownloadOutlined, ExperimentOutlined, ReloadOutlined, UploadOutlined } from "@ant-design/icons";
import { useNavigate, useSearchParams } from "react-router-dom";

import AppLayout from "../components/AppLayout";
import { formatApiError, default as apiClient } from "../api/client";
import { listDatasets } from "../api/datasets";
import {
  createQualityDemoDataset,
  createQualityLabelSnapshot,
  createQualityRun,
  downloadQualityAnnotationExport,
  downloadQualityArtifact,
  getQualityModel,
  getQualityRun,
  getQualitySample,
  listQualityLabelSnapshots,
  listQualityRuns,
  listQualitySamples,
  saveLabeledDataset,
  reviewQualityLabel,
  submitQualityLabel,
  type QualityRun,
  type QualityLabelMode,
  type QualityLabelSnapshot,
  type QualityModel,
  type QualityRuleConfig,
  type QualitySample,
  type QualitySampleDetail,
  trainQualityLabelSnapshot,
  uploadQualityDataset,
  validateQualityDataset,
} from "../api/spotWeldQuality";
import WaveformPanel from "../components/spotWeld/WaveformPanel";
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

const ANNOTATION_TYPES = [
  { key: "spot-weld", label: "点焊数据标注", description: "四通道波形、工艺参数与质量规则" },
  { key: "electrode", label: "电极柱极焊数据标注", description: "暂未开放" },
  { key: "filling", label: "加注数据标注", description: "暂未开放" },
  { key: "tightening", label: "拧紧数据标注", description: "暂未开放" },
  { key: "other", label: "其他", description: "暂未开放" },
] as const;

function qualityLabelText(value: string | null | undefined): string {
  if (!value) return "-";
  return LABEL_TEXT[value] || value;
}

function qualityRuleText(rule: { code: string; reason?: string }): string | undefined {
  return RULE_TEXT[rule.code] || rule.reason;
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
  const [snapshots, setSnapshots] = useState<QualityLabelSnapshot[]>([]);
  const [snapshotId, setSnapshotId] = useState("");
  const [snapshotName, setSnapshotName] = useState("approved-labels");
  const [snapshotLabelSource, setSnapshotLabelSource] = useState<"approved" | "automatic">("approved");
  const [qualityModel, setQualityModel] = useState<QualityModel | null>(null);
  const [qualityArtifacts, setQualityArtifacts] = useState<Record<string, string>>({});
  const [trainingSnapshot, setTrainingSnapshot] = useState(false);
  const [downloadingReport, setDownloadingReport] = useState(false);
  const [downloadingAnnotationExport, setDownloadingAnnotationExport] = useState(false);
  const [savingLabeledDataset, setSavingLabeledDataset] = useState(false);
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const [preparingRun, setPreparingRun] = useState(false);
  const [labelMode, setLabelMode] = useState<QualityLabelMode>(searchParams.get("mode") === "manual" ? "manual" : "automatic");
  const [ruleConfig, setRuleConfig] = useState<QualityRuleConfig>({ ...DEFAULT_RULE_CONFIG });
  const [workspaceMode, setWorkspaceMode] = useState(Boolean(searchParams.get("runId")));
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const activeContextRef = useRef({ projectId, runId });
  const detailRequestId = useRef(0);
  const runsRequestId = useRef(0);
  activeContextRef.current = { projectId, runId };

  const isCurrentContext = (expectedProjectId: string, expectedRunId: string) => (
    activeContextRef.current.projectId === expectedProjectId
    && activeContextRef.current.runId === expectedRunId
  );

  const selectedProject = useMemo(() => projects.find((item) => item.id === projectId), [projects, projectId]);
  const selectedRun = runs.find((item) => item.id === runId);
  const isSpotWeldFlow = searchParams.get("type") === "spot-weld"
    || Boolean(searchParams.get("runId") || searchParams.get("datasetId"));
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

  useEffect(() => {
    if (!projectId || !runId || selectedRun?.status !== "completed") {
      setSnapshots([]);
      setSnapshotId("");
      setQualityModel(null);
      setQualityArtifacts({});
      return;
    }
    let active = true;
    Promise.all([
      listQualityLabelSnapshots(projectId, runId),
      getQualityRun(projectId, runId),
      getQualityModel(projectId, runId).catch(() => null),
    ]).then(([nextSnapshots, run, model]) => {
      if (!active) return;
      setSnapshots(nextSnapshots);
      setSnapshotId((current) => nextSnapshots.some((item) => item.id === current) ? current : nextSnapshots[0]?.id || "");
      setQualityArtifacts(run.output_artifacts || {});
      setQualityModel(model);
    }).catch(() => {
      if (!active) return;
      setSnapshots([]);
      setQualityModel(null);
      setQualityArtifacts({});
    });
    return () => { active = false; };
  }, [projectId, runId, selectedRun?.status]);

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
      setLabel(detail.current_label || detail.automatic_label || "");
      setNote(detail.current_note || "");
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
      candidate_ids: [],
    });
    if (!validation.valid_rows || validation.errors.length) {
      const firstError = validation.errors[0];
      message.error(firstError?.code || "报告字段或波形校验失败");
      return;
    }
    const payload: Parameters<typeof createQualityRun>[1] = {
      dataset_artifact_id: nextDatasetArtifactId,
      field_mapping: {},
      candidate_ids: [],
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

  const openAnnotationType = (type: string) => {
    if (type !== "spot-weld") {
      message.info("该标注类型暂未开放");
      return;
    }
    setWorkspaceMode(false);
    setRunId("");
    setSearchParams((current) => {
      current.set("type", "spot-weld");
      current.set("view", "tasks");
      if (projectId) current.set("projectId", projectId);
      current.delete("runId");
      current.delete("datasetId");
      current.set("mode", "automatic");
      return current;
    }, { replace: true });
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

  const submitLabel = async () => {
    if (!projectId || !runId || !selected || !label) return;
    try {
      await submitQualityLabel(projectId, runId, selected.id, { label, note });
      message.success("标签已提交，等待审核");
      await refreshSamples(selected.id);
    } catch (error) { message.error(formatApiError(error, "标签提交失败")); }
  };

  const review = async (decision: "approved" | "returned") => {
    if (!projectId || !runId || !selected) return;
    try {
      await reviewQualityLabel(projectId, runId, selected.id, { decision, comment: reviewComment });
      message.success(decision === "approved" ? "审核已通过" : "已退回复核");
      await refreshSamples(selected.id);
    } catch (error) { message.error(formatApiError(error, "审核失败")); }
  };

  const createSnapshot = async () => {
    if (!projectId || !runId || !canReview) return;
    try {
      const snapshot = await createQualityLabelSnapshot(
        projectId,
        runId,
        snapshotName.trim() || (snapshotLabelSource === "automatic" ? "report-auto-labels" : "approved-labels"),
        snapshotLabelSource,
      );
      setSnapshots((current) => [snapshot, ...current.filter((item) => item.id !== snapshot.id)]);
      setSnapshotId(snapshot.id);
      message.success(snapshotLabelSource === "automatic" ? "已冻结报告复现自动标签快照" : "已冻结审核标签快照");
    } catch (error) {
      message.error(formatApiError(error, "创建标签快照失败"));
    }
  };

  const trainSnapshot = async () => {
    if (!projectId || !runId || !snapshotId || !canReview) return;
    setTrainingSnapshot(true);
    try {
      const result = await trainQualityLabelSnapshot(projectId, runId, snapshotId);
      setQualityModel(result.model);
      setQualityArtifacts(result.output_artifacts);
      setRuns((current) => current.map((run) => run.id === runId ? {
        ...run,
        output_artifacts: result.output_artifacts,
      } : run));
      message.success("质量模型与报告已生成");
    } catch (error) {
      message.error(formatApiError(error, "标签快照训练失败"));
    } finally {
      setTrainingSnapshot(false);
    }
  };

  const downloadReport = async () => {
    if (!projectId || !runId || !qualityArtifacts.report) return;
    setDownloadingReport(true);
    try {
      const blob = await downloadQualityArtifact(projectId, runId, "report");
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "spot-weld-quality-report.xlsx";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      message.error(formatApiError(error, "质量报告下载失败"));
    } finally {
      setDownloadingReport(false);
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
    const timer = window.setInterval(() => { void refreshRuns(); }, 1500);
    return () => window.clearInterval(timer);
  }, [projectId, runId, selectedRun?.status]);

  const catalogView = (
    <>
      <div className="page-header">
        <div className="page-header-copy">
          <p className="page-kicker">QUALITY / LABELING</p>
          <h2 className="page-title">数据标注</h2>
          <p className="page-subtitle">选择数据类型进入对应标注流程</p>
        </div>
      </div>
      <section className="data-annotation__catalog" aria-label="标注类型">
        {ANNOTATION_TYPES.map((type) => (
          <button
            type="button"
            key={type.key}
            className={`data-annotation__type ${type.key === "spot-weld" ? "is-available" : "is-disabled"}`}
            aria-label={type.label}
            onClick={() => openAnnotationType(type.key)}
          >
            <strong>{type.label}</strong>
            <span>{type.description}</span>
            <Tag color={type.key === "spot-weld" ? "blue" : "default"}>{type.key === "spot-weld" ? "已开放" : "暂未开放"}</Tag>
          </button>
        ))}
      </section>
    </>
  );

  const tasksView = (
    <>
      <div className="page-header">
        <div className="page-header-copy">
          <p className="page-kicker">SPOT WELD / TASKS</p>
          <h2 className="page-title">点焊标注任务</h2>
          <p className="page-subtitle">查看任务状态、标注方式和当前进度</p>
        </div>
        <div className="data-annotation__task-actions">
          <button type="button" className="ant-btn" onClick={() => openSetup("manual")}>新建手动标注任务</button>
          <button type="button" className="ant-btn ant-btn-primary" onClick={() => openSetup("automatic")}>新建自动标注任务</button>
        </div>
      </div>
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
            <button
              type="button"
              className="ant-btn"
              aria-label={`${run.label_mode === "manual" ? "手工标注" : "查看标注"} ${run.id}`}
              onClick={() => openRunWorkspace(run)}
            >
              {run.label_mode === "manual" ? "手工标注" : "查看标注"}
            </button>
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
        <button type="button" className="ant-btn" onClick={() => { setWorkspaceMode(false); setRunId(""); navigate("/data-annotation?type=spot-weld&view=tasks"); }}>返回任务列表</button>
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
          <p className="page-subtitle">{selectedProject?.name || "选择项目后开始审核点焊波形"}</p>
        </div>
        <div className="spot-weld-annotation__controls">
          <label htmlFor="spot-weld-annotation-project">Project</label>
          <select id="spot-weld-annotation-project" className="spot-weld-annotation__project" aria-label="Project" value={projectId} onChange={(event) => { setProjectId(event.target.value); setRunId(""); }} disabled={loadingProjects}>
            <option value="">选择项目</option>
            {projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
          </select>
          <label htmlFor="spot-weld-quality-run">质量运行</label>
          <select id="spot-weld-quality-run" className="spot-weld-annotation__run" aria-label="质量运行" value={runId} onChange={(event) => setRunId(event.target.value)} disabled={!projectId || loadingRuns}>
            <option value="">选择运行</option>
            {runs.map((run) => <option value={run.id} key={run.id}>{run.id.slice(0, 8)} · {run.status}</option>)}
          </select>
        </div>
        <div className="spot-weld-annotation__actions">
          <Dropdown trigger={["click"]} disabled={!canCreate || preparingRun} menu={{ items: [{ key: "60", label: "快速样本（60 条）" }, { key: "1875", label: "报告复现（1875 条）" }], onClick: ({ key }) => { void handleCreateDemo(Number(key)); } }}>
            <Tooltip title="准备报告结构的模拟数据"><button type="button" className="ant-btn" disabled={!canCreate || preparingRun}><ExperimentOutlined />模拟数据</button></Tooltip>
          </Dropdown>
          {projectId && selectedRun && <Dropdown trigger={["click"]} disabled={downloadingAnnotationExport} menu={{ items: [{ key: "csv", label: "CSV" }, { key: "xlsx", label: "XLSX" }], onClick: ({ key }) => { void downloadAnnotations(key as "csv" | "xlsx"); } }}>
            <button type="button" className="ant-btn" aria-label="导出标注" disabled={downloadingAnnotationExport}><DownloadOutlined />导出标注</button>
          </Dropdown>}
          {projectId && selectedRun?.status === "completed" && <button type="button" className="ant-btn ant-btn-primary" aria-label="保存到数据管理" onClick={() => void saveToDataManagement()} disabled={!canLabel || savingLabeledDataset}>{savingLabeledDataset ? "保存中..." : "保存到数据管理"}</button>}
          <Tooltip title="刷新质量运行"><button type="button" className="ant-btn ant-btn-icon-only" aria-label="刷新质量运行" onClick={() => { void refreshRuns(); }} disabled={!projectId || loadingRuns}><ReloadOutlined /></button></Tooltip>
        </div>
      </div>
      <div className="spot-weld-annotation__workspace">
        <section className="spot-weld-annotation__region spot-weld-annotation__queue" aria-labelledby="spot-weld-queue-title">
          <div className="spot-weld-annotation__region-head"><h3 id="spot-weld-queue-title">{labels.queue || "样本队列"}</h3><div className="spot-weld-annotation__queue-meta"><Tag>{samples.length} samples</Tag>{selectedRun && <Tag color="blue">{annotationProgressText(selectedRun)}</Tag>}</div></div>
          {loadingRuns || loadingSamples ? <Spin /> : samples.length === 0 ? <Empty description="暂无样本" /> : (
            <div className="spot-weld-annotation__sample-list">
              {samples.map((sample) => <button type="button" className={`spot-weld-annotation__sample ${selected?.id === sample.id ? "is-selected" : ""}`} key={sample.id} onClick={() => selectSample(sample)} aria-label={sample.display_id}>
                <span><strong>{sample.display_id}</strong><small>row {sample.source_row_index ?? "-"}</small></span>
                <Tag color={warningColor[sample.warning_level || "none"]}>{sample.warning_level || "none"}</Tag>
              </button>)}
            </div>
          )}
        </section>
        <section className="spot-weld-annotation__region spot-weld-annotation__waveforms" aria-labelledby="spot-weld-waveform-title">
          <div className="spot-weld-annotation__region-head"><h3 id="spot-weld-waveform-title">{labels.waveforms || "四通道波形"}</h3>{selectedRun && <Tag color={selectedRun.status === "completed" ? "green" : "blue"}>{selectedRun.status}</Tag>}</div>
          {loadingDetail ? <Spin /> : selected ? <WaveformPanel waveforms={selected.waveforms} /> : <Empty description="选择样本查看波形" />}
        </section>
        <section className="spot-weld-annotation__region spot-weld-annotation__review" aria-labelledby="spot-weld-review-title">
          <h3 id="spot-weld-review-title">{labels.review || "标注与审核"}</h3>
          {selected ? <>
            <div className="spot-weld-annotation__sample-meta"><strong>{selected.display_id}</strong><Tag color={warningColor[selected.warning_level || "none"]}>{selected.warning_level || "none"}</Tag><span>{selected.defect_probability == null ? "-" : `${(selected.defect_probability * 100).toFixed(1)}% defect`}</span></div>
            {selectedRun?.label_mode !== "manual" && <>
              <div className="spot-weld-annotation__evidence"><span>自动标签 <strong>{qualityLabelText(selected.automatic_label)}</strong></span><span>聚类 <strong>{selected.cluster_id == null ? "-" : selected.cluster_id}</strong></span><span>特征 <strong>{Object.keys(selected.feature_values || {}).length || "-"}</strong></span></div>
              <div className="spot-weld-annotation__rules" aria-label="规则命中">{(selected.rule_hits || []).length ? selected.rule_hits?.map((rule) => <span className="spot-weld-annotation__rule" key={rule.code}><Tag color="blue">{qualityLabelText(rule.label)}</Tag>{qualityRuleText(rule) && <small>{qualityRuleText(rule)}</small>}</span>) : <small>无规则命中</small>}</div>
            </>}
            <details className="spot-weld-annotation__details"><summary>工艺参数</summary><div>{Object.entries(selected.table_values || {}).map(([name, value]) => <span key={name}><small>{name}</small><strong>{typeof value === "number" ? value.toFixed(3) : String(value)}</strong></span>)}</div></details>
            <label htmlFor="quality-label">人工标签</label>
            <select id="quality-label" aria-label="人工标签" value={label} onChange={(event) => setLabel(event.target.value)} disabled={!canLabel}><option value="">请选择</option>{LABEL_OPTIONS.map(([value, text]) => <option value={value} key={value}>{text}</option>)}</select>
            <label htmlFor="quality-note">备注</label><textarea id="quality-note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="记录工艺判断" disabled={!canLabel} />
            <button type="button" className="ant-btn ant-btn-primary" onClick={submitLabel} disabled={!canLabel || !label}>提交复核</button>
            <div className="spot-weld-annotation__review-divider" /><label htmlFor="quality-review-comment">审核意见</label><textarea id="quality-review-comment" value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} placeholder="审核说明" disabled={!canReview} />
            <div className="spot-weld-annotation__review-actions"><button type="button" className="ant-btn ant-btn-primary" onClick={() => review("approved")} disabled={!canReview}>通过审核</button><button type="button" className="ant-btn" onClick={() => review("returned")} disabled={!canReview}>退回</button></div>
            <small className="spot-weld-annotation__status">状态：{selected.review_status}</small>
          </> : <Empty description="选择样本进行标注" />}
          {runId && selectedRun?.status === "completed" && <section className="spot-weld-annotation__training" aria-label="审核标签训练">
            <div className="spot-weld-annotation__training-head"><h4>审核标签训练</h4><Tag>{snapshots.length} 快照</Tag></div>
            <label htmlFor="quality-snapshot-name">快照名称</label><input id="quality-snapshot-name" aria-label="快照名称" value={snapshotName} onChange={(event) => setSnapshotName(event.target.value)} disabled={!canReview} />
            <label htmlFor="quality-snapshot-source">快照标签来源</label><select id="quality-snapshot-source" aria-label="快照标签来源" value={snapshotLabelSource} onChange={(event) => setSnapshotLabelSource(event.target.value as "approved" | "automatic")} disabled={!canReview}><option value="approved">已人工审核</option><option value="automatic">报告复现自动标签</option></select>
            <button type="button" className="ant-btn" onClick={createSnapshot} disabled={!canReview}>创建训练快照</button>
            <label htmlFor="quality-training-snapshot">训练标签快照</label><select id="quality-training-snapshot" aria-label="训练标签快照" value={snapshotId} onChange={(event) => setSnapshotId(event.target.value)} disabled={!canReview || snapshots.length === 0}><option value="">选择已冻结快照</option>{snapshots.map((snapshot) => <option value={snapshot.id} key={snapshot.id}>{snapshot.name} · {snapshot.label_source === "automatic" ? "报告复现自动标签" : "已人工审核"} · {snapshot.sample_count} 条</option>)}</select>
            <button type="button" className="ant-btn ant-btn-primary" onClick={trainSnapshot} disabled={!canReview || !snapshotId || trainingSnapshot}>{trainingSnapshot ? "训练中..." : "训练快照"}</button>
            {qualityModel && <div className="spot-weld-annotation__training-result"><div><strong>{qualityModel.name}</strong><small>{qualityModel.backbone || qualityModel.framework || "质量模型"}</small></div><div className="spot-weld-annotation__training-actions">{qualityArtifacts.report && <button type="button" className="ant-btn" aria-label="下载质量报告" onClick={downloadReport} disabled={downloadingReport}><DownloadOutlined />下载质量报告</button>}<button type="button" className="ant-btn" onClick={() => navigate(`/models?projectId=${encodeURIComponent(projectId)}`)}>查看模型库</button></div></div>}
          </section>}
        </section>
      </div>
    </>
  );

  return (
    <AppLayout>
      <div className="page-shell fade-in spot-weld-annotation">
        {!isSpotWeldFlow ? catalogView : isTaskList ? (loadingProjects ? <div className="data-annotation__loading"><Spin /></div> : tasksView) : isSetup ? (loadingProjects || loadingDatasets ? <div className="data-annotation__loading"><Spin /></div> : setupView) : workspaceView}
      </div>
    </AppLayout>
  );
}
