import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { App as AntApp, Dropdown, Empty, Modal, Spin, Steps, Table, Tag, Tooltip } from "antd";
import { DeleteOutlined, DownloadOutlined, EyeOutlined, LeftOutlined, ReloadOutlined, RightOutlined, UploadOutlined } from "@ant-design/icons";
import { useNavigate, useSearchParams } from "react-router-dom";
import * as echarts from "echarts";

import AppLayout from "../components/AppLayout";
import DeleteConfirmation from "../components/DeleteConfirmation";
import TableRowAction from "../components/TableRowAction";
import LabelSchemaEditor, { type LabelColumnDraft } from "../components/LabelSchemaEditor";
import AutomaticAnnotationStrategyEditor, {
  createAutomaticStrategyDraft,
  createAutomaticRule,
  type AutomaticRuleDraft,
  type AutomaticAnnotationSourceColumn,
  type AutomaticStrategyDraft,
  type ClusterOption,
} from "../components/AutomaticAnnotationStrategyEditor";
import { useI18n } from "../i18n";
import { normalizeTaskStatus, taskStatusColor, taskStatusLabel } from "../utils/taskStatus";
import { formatApiError, default as apiClient } from "../api/client";
import { listDatasets, listDatasetVersions, type DatasetVersionOption } from "../api/datasets";
import { listAnnotationModelVersions, type AnnotationModelVersion, type AnnotationOutputColumn } from "../api/models";
import { createLabelSchema } from "../api/labelSchemas";
import {
  createAnnotationPreview,
  getAnnotationPreview,
  listAnnotationPreviewSamples,
  listAnnotationExecutionResults,
  listAnnotationExecutionStats,
  listAnnotationOperations,
  listAnnotationTasks,
  createGenericAnnotationTask,
  updateGenericAnnotationTaskConfiguration,
  transitionAnnotationTask,
  type AnnotationPreview,
  type AnnotationTask,
  type AnnotationOperation,
} from "../api/annotationTasks";
import PreviewDrawer from "../components/PreviewDrawer";
import ReturnAcceptancePanel from "../components/ReturnAcceptancePanel";
import AnnotationCommentModerationPanel from "../components/AnnotationCommentModerationPanel";
import AssignmentDialog from "../components/AssignmentDialog";
import ClusterPreviewPanel, { type ClusterEvaluation } from "../components/ClusterPreviewPanel";
import { createAssignments, listAnnotatorSubjects, type AnnotatorSubject, type SampleScope } from "../api/annotatorAssignments";
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
import { deleteAnnotationTask } from "../api/annotationTasks";
import type { QualityClusterPreview } from "../api/spotWeldQuality";

interface ProjectOption { id: string; name: string; project_role?: string; }

interface DatasetOption {
  id?: string;
  artifact_id?: string;
  name?: string;
  format?: string;
  row_count?: number;
}

interface PreviewDrawerState {
  snapshot?: Record<string, unknown>;
  loading?: boolean;
  sampleTotal?: number;
  taskId: string;
  previewId?: string;
  operationId?: string;
  taskRevision: number;
  status?: string;
  summary?: Record<string, unknown>;
  strategySummary?: Record<string, unknown>;
  progress?: number;
  errorMessage?: string | null;
  samples: Array<{ sample_id: string; row_index: number; values: Record<string, unknown> }>;
  sampleCursor?: string | null;
}

interface RevisionConflictState {
  taskId: string;
  attemptedRevision: number;
  currentRevision?: number;
  labels?: Record<string, unknown>;
  message: string;
}

type GenericAutomaticConfiguration = Record<string, unknown>;

type ExecutionStatsKind = "sample" | "cluster" | "rule" | "final_label";

interface ExecutionViewState {
  operation: AnnotationOperation;
  results: Array<{ id: string; sample_id: string; row_index: number; status: string; values: Record<string, unknown>; provenance: Record<string, unknown> }>;
  resultsCursor: string | null;
  statsKind: ExecutionStatsKind;
  stats: Array<Record<string, unknown>>;
  statsCursor: string | null;
  loading: boolean;
  error: string | null;
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
  const status = run.label_mode === "manual"
    ? (normalizeTaskStatus(run.status) === "completed" ? "completed" : "running")
    : run.status;
  return taskStatusLabel(status, lang);
}

function runStatusColor(run: QualityRun): string {
  const status = run.label_mode === "manual"
    ? (normalizeTaskStatus(run.status) === "completed" ? "completed" : "running")
    : run.status;
  return taskStatusColor(status);
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

function isRevisionConflict(error: unknown): boolean {
  return Number((error as any)?.response?.status) === 409;
}

function revisionConflictFromError(error: any, task: AnnotationTask): RevisionConflictState {
  const detail = error?.response?.data?.detail;
  const payload = detail && typeof detail === "object" ? detail : {};
  const currentRevision = Number(payload.current_revision ?? payload.task_revision ?? payload.revision);
  const labels = payload.labels && typeof payload.labels === "object" ? payload.labels as Record<string, unknown> : undefined;
  return {
    taskId: task.id,
    attemptedRevision: task.task_revision,
    currentRevision: Number.isFinite(currentRevision) ? currentRevision : undefined,
    labels,
    message: String(payload.message || "任务修订已变化，请确认服务端最新状态后重试"),
  };
}

function outputColumnsFromSnapshot(task: AnnotationTask): AnnotationOutputColumn[] {
  const configuration = task.task_snapshot?.configuration as Record<string, unknown> | undefined;
  const outputContract = configuration?.model_output_contract as { columns?: unknown } | undefined;
  if (Array.isArray(outputContract?.columns)) {
    return outputContract.columns.filter((column): column is AnnotationOutputColumn => Boolean(
      column && typeof column === "object"
      && typeof (column as AnnotationOutputColumn).machine_key === "string"
      && typeof (column as AnnotationOutputColumn).display_name === "string"
      && ["string", "int", "float"].includes((column as AnnotationOutputColumn).value_type),
    ));
  }
  const schema = task.task_snapshot?.label_schema as { columns?: unknown } | undefined;
  return Array.isArray(schema?.columns) ? schema.columns.flatMap((column) => {
    if (!column || typeof column !== "object") return [];
    const item = column as Record<string, unknown>;
    const machineKey = typeof item.machine_key === "string" ? item.machine_key : "";
    const displayName = typeof item.display_name === "string" ? item.display_name : machineKey;
    const valueType = item.value_type;
    return machineKey && ["string", "int", "float"].includes(String(valueType))
      ? [{ machine_key: machineKey, display_name: displayName, value_type: valueType as AnnotationOutputColumn["value_type"], required: Boolean(item.required) }]
      : [];
  }) : [];
}

function sourceColumnsFromSnapshot(task: AnnotationTask): AutomaticAnnotationSourceColumn[] {
  const datasetVersion = task.task_snapshot?.dataset_version as { columns?: unknown } | undefined;
  if (Array.isArray(datasetVersion?.columns)) {
    const columns = datasetVersion.columns.flatMap((column) => {
      if (!column || typeof column !== "object") return [];
      const item = column as Record<string, unknown>;
      const name = typeof item.name === "string" ? item.name : "";
      return name ? [{ name, dtype: typeof item.dtype === "string" ? item.dtype : "string" }] : [];
    });
    if (columns.length) return columns;
  }
  return Array.isArray(task.task_snapshot?.visible_columns)
    ? task.task_snapshot.visible_columns.map((name) => ({ name: String(name), dtype: "string" }))
    : [];
}

function valueText(value: unknown): string {
  return value == null ? "" : String(value);
}

function strategyDraftFromTask(task: AnnotationTask, columns: AnnotationOutputColumn[]): AutomaticStrategyDraft {
  const configuration = (task.task_snapshot?.configuration || {}) as Record<string, unknown>;
  const rules = Array.isArray(configuration.rules) ? configuration.rules.flatMap((raw, index) => {
    if (!raw || typeof raw !== "object") return [];
    const rule = raw as Record<string, unknown>;
    const rawWhen = rule.when as Record<string, unknown> | undefined;
    const group = rawWhen && (rawWhen.all || rawWhen.any);
    const rawConditions = Array.isArray(group) ? group : rawWhen ? [rawWhen] : [];
    const conditions = rawConditions.flatMap((condition, conditionIndex) => {
      if (!condition || typeof condition !== "object") return [];
      const [field, operations] = Object.entries(condition as Record<string, unknown>)[0] || [];
      if (!field || !operations || typeof operations !== "object") return [];
      const [operator, rawValue] = Object.entries(operations as Record<string, unknown>)[0] || [];
      if (!operator) return [];
      return [{ id: `${String(rule.id || `rule-${index}`)}-condition-${conditionIndex}`, field, operator: operator as any, value: valueText(rawValue) }];
    });
    if (!conditions.length) return [];
    return [{
      id: String(rule.id || `rule-${index}`),
      priority: Number.isInteger(rule.priority) ? Number(rule.priority) : 0,
      join: rawWhen && Array.isArray(rawWhen.any) ? "any" : "all",
      conditions,
      values: Object.fromEntries(columns.map((column) => [column.machine_key, valueText((rule.values as Record<string, unknown> | undefined)?.[column.machine_key])])),
      clusterIds: Array.isArray(rule.cluster_ids) ? rule.cluster_ids.map(String).join(",") : "",
    } satisfies AutomaticRuleDraft];
  }) : [];
  const selectedClusters = Array.isArray(configuration.selected_clusters) ? configuration.selected_clusters.map(String) : [];
  const rawClusterLabels = configuration.cluster_labels && typeof configuration.cluster_labels === "object" ? configuration.cluster_labels as Record<string, Record<string, unknown>> : {};
  return {
    strategy: ["cluster", "rule", "cluster_rule"].includes(String(configuration.strategy)) ? configuration.strategy as AutomaticStrategyDraft["strategy"] : "cluster",
    selectedClusters,
    otherValues: Object.fromEntries(columns.map((column) => [column.machine_key, valueText((configuration.other_values as Record<string, unknown> | undefined)?.[column.machine_key])])),
    clusterLabels: Object.fromEntries(Object.entries(rawClusterLabels).map(([clusterId, values]) => [clusterId, Object.fromEntries(columns.map((column) => [column.machine_key, valueText(values?.[column.machine_key])]))])),
    rules: rules.length ? rules : [createAutomaticRule(columns)],
  };
}

function typedAutomaticValue(column: AnnotationOutputColumn, raw: string): { value?: string | number; error?: string } {
  if (column.value_type === "string") return raw.trim() ? { value: raw } : { error: `${column.display_name} 不能为空` };
  if (column.value_type === "int") {
    return /^[-+]?\d+$/.test(raw.trim()) ? { value: Number(raw) } : { error: `${column.display_name} 必须是整数` };
  }
  const numeric = Number(raw);
  return raw.trim() && Number.isFinite(numeric) ? { value: numeric } : { error: `${column.display_name} 必须是有限浮点数` };
}

function sourceColumnValueType(dtype: string): "int" | "float" | "boolean" | "string" {
  const normalized = dtype.trim().toLowerCase();
  if (normalized.includes("int") || normalized.includes("uint")) return "int";
  if (normalized.includes("float") || normalized.includes("double") || normalized.includes("decimal") || normalized === "number") return "float";
  if (normalized === "bool" || normalized === "boolean") return "boolean";
  return "string";
}

function typedRuleConditionValue(
  field: string,
  operator: string,
  raw: string,
  sourceColumns: AutomaticAnnotationSourceColumn[],
): { value?: string | number | boolean | Array<string | number | boolean>; error?: string } {
  const sourceColumn = sourceColumns.find((column) => column.name === field);
  if (!sourceColumn) return { error: `规则字段 ${field} 不在冻结数据版本中` };
  if (["is_null", "not_null"].includes(operator)) return { value: true };
  const valueType = sourceColumnValueType(sourceColumn.dtype);
  if (["gt", "gte", "lt", "lte"].includes(operator) && !["int", "float"].includes(valueType)) {
    return { error: `规则字段 ${field} 不是数值列，不能使用数值比较` };
  }
  const rawValues = ["in", "not_in"].includes(operator) ? raw.split(",").map((item) => item.trim()).filter(Boolean) : [raw.trim()];
  if (!rawValues.length || rawValues.some((value) => !value)) return { error: `规则字段 ${field} 的比较值不能为空` };
  const values = rawValues.map((value) => {
    if (valueType === "string") return { value };
    if (valueType === "boolean") {
      if (["true", "1"].includes(value.toLowerCase())) return { value: true };
      if (["false", "0"].includes(value.toLowerCase())) return { value: false };
      return { error: `规则字段 ${field} 必须是 true 或 false` };
    }
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || (valueType === "int" && !Number.isInteger(numeric))) {
      return { error: `规则字段 ${field} 必须是${valueType === "int" ? "整数" : "有限浮点数"}` };
    }
    return { value: numeric };
  });
  const invalid = values.find((item) => item.error);
  if (invalid?.error) return { error: invalid.error };
  const normalized = values.map((item) => item.value!);
  return { value: ["in", "not_in"].includes(operator) ? normalized : normalized[0] };
}

function automaticConfigurationFromDraft(
  draft: AutomaticStrategyDraft,
  columns: AnnotationOutputColumn[],
  sourceColumns: AutomaticAnnotationSourceColumn[],
  clustering: boolean,
  discovery: boolean,
): { configuration?: GenericAutomaticConfiguration; error?: string } {
  if (!clustering) return { configuration: { clustering: false, strategy: "model" } };
  if (discovery) return { configuration: { clustering: true, cluster_discovery: true } };
  const otherValues: Record<string, string | number> = {};
  for (const column of columns) {
    const result = typedAutomaticValue(column, draft.otherValues[column.machine_key] || "");
    if (result.error) return { error: result.error };
    otherValues[column.machine_key] = result.value!;
  }
  const rules = [] as Array<Record<string, unknown>>;
  if (draft.strategy === "rule" || draft.strategy === "cluster_rule") {
    for (const rule of draft.rules) {
      const conditions = rule.conditions.map((condition) => {
        if (!condition.field || (!condition.value.trim() && !["is_null", "not_null"].includes(condition.operator))) return null;
        const result = typedRuleConditionValue(condition.field, condition.operator, condition.value, sourceColumns);
        return result.error ? result : { [condition.field]: { [condition.operator]: result.value } };
      });
      if (!conditions.length || conditions.some((condition) => condition === null)) return { error: "规则条件不完整" };
      const invalidCondition = conditions.find((condition) => condition && "error" in condition) as { error?: string } | undefined;
      if (invalidCondition?.error) return { error: invalidCondition.error };
      const values: Record<string, string | number> = {};
      for (const column of columns) {
        const raw = rule.values[column.machine_key] || "";
        if (!raw.trim()) continue;
        const result = typedAutomaticValue(column, raw);
        if (result.error) return { error: `规则 ${rule.id}：${result.error}` };
        values[column.machine_key] = result.value!;
      }
      if (!Object.keys(values).length) return { error: "每条规则至少需要一个命中标签值" };
      rules.push({
        id: rule.id,
        priority: Number.isInteger(rule.priority) ? rule.priority : 0,
        when: conditions.length === 1 ? conditions[0] : { [rule.join]: conditions },
        values,
        ...(rule.clusterIds.trim() ? { cluster_ids: rule.clusterIds.split(",").map((item) => item.trim()).filter(Boolean) } : {}),
      });
    }
  }
  const configuration: GenericAutomaticConfiguration = {
    clustering: true,
    strategy: draft.strategy,
    other_values: otherValues,
    ...(rules.length ? { rules } : {}),
  };
  if (!discovery && (draft.strategy === "cluster" || draft.strategy === "cluster_rule")) {
    if (!draft.selectedClusters.length) return { error: "至少选择一个簇" };
    const clusterLabels: Record<string, Record<string, string | number>> = {};
    for (const clusterId of draft.selectedClusters) {
      const labels: Record<string, string | number> = {};
      for (const column of columns) {
        const result = typedAutomaticValue(column, draft.clusterLabels[clusterId]?.[column.machine_key] || "");
        if (result.error) return { error: `簇 ${clusterId}：${result.error}` };
        labels[column.machine_key] = result.value!;
      }
      clusterLabels[clusterId] = labels;
    }
    configuration.selected_clusters = draft.selectedClusters;
    configuration.cluster_labels = clusterLabels;
  }
  return { configuration };
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
  const [genericTasks, setGenericTasks] = useState<AnnotationTask[]>([]);
  const [annotationOperations, setAnnotationOperations] = useState<AnnotationOperation[]>([]);
  const [annotationOperationsCursor, setAnnotationOperationsCursor] = useState<string | null>(null);
  const [commentTaskId, setCommentTaskId] = useState<string | null>(null);
  const [executionView, setExecutionView] = useState<ExecutionViewState | null>(null);
  const [operationsLoading, setOperationsLoading] = useState(false);
  const [genericTaskLoading, setGenericTaskLoading] = useState(false);
  const [previewDrawer, setPreviewDrawer] = useState<PreviewDrawerState | null>(null);
  const [assignmentTask, setAssignmentTask] = useState<AnnotationTask | null>(null);
  const [annotators, setAnnotators] = useState<AnnotatorSubject[]>([]);
  const [assignmentLoading, setAssignmentLoading] = useState(false);
  const [assignmentOverlapWarning, setAssignmentOverlapWarning] = useState<string | null>(null);
  const [revisionConflict, setRevisionConflict] = useState<RevisionConflictState | null>(null);
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [genericVersions, setGenericVersions] = useState<DatasetVersionOption[]>([]);
  const [genericModelVersions, setGenericModelVersions] = useState<AnnotationModelVersion[]>([]);
  const [genericVersionId, setGenericVersionId] = useState("");
  const [genericTaskName, setGenericTaskName] = useState("");
  const [genericCompletionCriteria, setGenericCompletionCriteria] = useState("");
  const [genericDueAt, setGenericDueAt] = useState(() => new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10));
  const [genericScopeMode, setGenericScopeMode] = useState<"all" | "filter">("all");
  const [genericScopeConditions, setGenericScopeConditions] = useState<Array<{ id: string; column: string; operator: string; value: string }>>([]);
  const [genericVisibleColumns, setGenericVisibleColumns] = useState<string[]>([]);
  const [genericTasksCursor, setGenericTasksCursor] = useState<string | null>(null);
  const [editConfigTask, setEditConfigTask] = useState<AnnotationTask | null>(null);
  const [editConfigDraft, setEditConfigDraft] = useState<{ name: string; instructions: string; completionCriteria: string; dueAt: string; visibleColumns: string[] }>({ name: "", instructions: "", completionCriteria: "", dueAt: "", visibleColumns: [] });
  const [editConfigSaving, setEditConfigSaving] = useState(false);
  const [genericSchemaName, setGenericSchemaName] = useState("labels");
  const [genericLabelKey, setGenericLabelKey] = useState("label");
  const [genericLabelType, setGenericLabelType] = useState<"string" | "int" | "float">("string");
  const [genericSchemaInstruction, setGenericSchemaInstruction] = useState("");
  const [genericInstructions, setGenericInstructions] = useState("");
  const [genericModelVersionId, setGenericModelVersionId] = useState("");
  const [genericClustering, setGenericClustering] = useState(false);
  const [genericAutoLabelSource, setGenericAutoLabelSource] = useState<"model" | "custom">("model");
  const [genericAutoSchema, setGenericAutoSchema] = useState<{ id: string; columns: AnnotationOutputColumn[] } | null>(null);
  const [genericSetupStep, setGenericSetupStep] = useState<1 | 2>(1);
  const [genericDiscoveryTask, setGenericDiscoveryTask] = useState<AnnotationTask | null>(null);
  const [genericDiscoveryPreviewId, setGenericDiscoveryPreviewId] = useState<string | null>(null);
  const [genericDiscoveryError, setGenericDiscoveryError] = useState<string | null>(null);
  const [genericFinalPreviewId, setGenericFinalPreviewId] = useState<string | null>(null);
  const [genericFinalPreviewError, setGenericFinalPreviewError] = useState<string | null>(null);
  const [genericFinalStage, setGenericFinalStage] = useState(false);
  const [genericFinalAttempt, setGenericFinalAttempt] = useState(0);
  const [genericFinalSamples, setGenericFinalSamples] = useState<Awaited<ReturnType<typeof listAnnotationPreviewSamples>> | null>(null);
  const [genericAutomaticDraft, setGenericAutomaticDraft] = useState<AutomaticStrategyDraft>(() => createAutomaticStrategyDraft([]));
  const [automaticConfigTask, setAutomaticConfigTask] = useState<AnnotationTask | null>(null);
  const [automaticConfigDraft, setAutomaticConfigDraft] = useState<AutomaticStrategyDraft>(() => createAutomaticStrategyDraft([]));
  const [automaticConfigSaving, setAutomaticConfigSaving] = useState(false);
  const [genericCreating, setGenericCreating] = useState(false);
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
  const [labelSchemaId, setLabelSchemaId] = useState("");
  const [qualityModels, setQualityModels] = useState<QualityModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [automaticSetupStep, setAutomaticSetupStep] = useState<1 | 2>(1);
  const [weakSupervision, setWeakSupervision] = useState(false);
  const [labelDtype, setLabelDtype] = useState<CreatedTargetColumnDtype>("string");
  const [annotationRules, setAnnotationRules] = useState<AnnotationRule[]>([
    { id: "rule-1", kind: "condition", label: "", tokens: [
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
  const [genericSetupMode, setGenericSetupMode] = useState(() => (
    searchParams.get("view") === "setup" && searchParams.get("type") !== "spot-weld"
  ));
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
  const selectedGenericModelVersion = useMemo(
    () => genericModelVersions.find((item) => item.id === genericModelVersionId),
    [genericModelVersions, genericModelVersionId],
  );
  const selectedGenericOutputColumns = selectedGenericModelVersion?.output_contract?.columns || [];
  // 弱监督任务（§7.1 步骤 5）的标签列可由用户指定；未指定时沿用模型输出合同。
  const effectiveAutoColumns = genericAutoLabelSource === "custom" && genericAutoSchema
    ? genericAutoSchema.columns
    : selectedGenericOutputColumns;
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
    if (!isTaskList || !projectId) {
      setGenericTasks([]);
      setGenericTasksCursor(null);
      setAnnotationOperations([]);
      setAnnotationOperationsCursor(null);
      return;
    }
    let active = true;
    setGenericTaskLoading(true);
    listAnnotationTasks(projectId)
      .then((result) => {
        if (!active) return;
        setGenericTasks(result.items || []);
        setGenericTasksCursor(result.next_cursor || null);
      })
      .catch((error) => { if (active) { setGenericTasks([]); setGenericTasksCursor(null); message.error(formatApiError(error, "通用任务加载失败")); } })
      .finally(() => { if (active) setGenericTaskLoading(false); });
    return () => { active = false; };
  }, [isTaskList, projectId]);

  const loadMoreGenericTasks = async () => {
    if (!projectId || !genericTasksCursor || genericTaskLoading) return;
    setGenericTaskLoading(true);
    try {
      const result = await listAnnotationTasks(projectId, 50, genericTasksCursor);
      setGenericTasks((current) => {
        const seen = new Set(current.map((item) => item.id));
        return [...current, ...(result.items || []).filter((item) => !seen.has(item.id))];
      });
      setGenericTasksCursor(result.next_cursor || null);
    } catch (error) {
      message.error(formatApiError(error, "通用任务加载失败"));
    } finally {
      setGenericTaskLoading(false);
    }
  };

  useEffect(() => {
    if (!isTaskList || !projectId) {
      setAnnotationOperations([]);
      setAnnotationOperationsCursor(null);
      return;
    }
    let active = true;
    setOperationsLoading(true);
    listAnnotationOperations(projectId)
      .then((result) => { if (active) { setAnnotationOperations(result.items || []); setAnnotationOperationsCursor(result.next_cursor || null); } })
      .catch((error) => { if (active) { setAnnotationOperations([]); setAnnotationOperationsCursor(null); message.error(formatApiError(error, "通用操作加载失败")); } })
      .finally(() => { if (active) setOperationsLoading(false); });
    return () => { active = false; };
  }, [isTaskList, projectId, message]);

  useEffect(() => {
    if (!previewDrawer?.previewId) return undefined;
    const taskId = previewDrawer.taskId;
    const previewId = previewDrawer.previewId;
    const operationId = previewDrawer.operationId;
    let active = true;
    let timer: ReturnType<typeof setInterval> | undefined;
    const refresh = async () => {
      try {
        const preview = await getAnnotationPreview(taskId, previewId);
        if (!active) return;
        const previewStatus = String(preview.status);
        const previewSummary = preview.summary || {};
        const taskStatus = previewStatus === "completed" || previewStatus === "ready"
          ? (previewSummary.configuration_complete === false || Number(previewSummary.needs_review_count || 0) > 0 ? "needs_review" : "preview_ready")
          : previewStatus === "failed" || previewStatus === "cancelled"
            ? previewStatus
            : "previewing";
        setGenericTasks((items) => items.map((item) => item.id === taskId && item.task_revision === preview.task_revision
          ? {
              ...item,
              status: ["draft", "previewing", "failed", "needs_review"].includes(item.status) ? taskStatus : item.status,
              preview: {
                ...preview,
                id: preview.id || previewId,
                operation_id: preview.operation_id || operationId || null,
              },
            }
          : item));
        setPreviewDrawer((current) => current ? {
          ...current,
          status: previewStatus,
          progress: preview.progress,
          summary: preview.summary || current.summary,
          strategySummary: preview.strategy_summary || current.strategySummary,
          errorMessage: preview.error_code || preview.error?.message || null,
        } : current);
        const terminal = ["completed", "ready", "failed", "cancelled"].includes(previewStatus);
        if (terminal && timer) clearInterval(timer);
        if (terminal && previewStatus !== "failed" && previewStatus !== "cancelled") {
          const page = await listAnnotationPreviewSamples(taskId, previewId, 50);
          if (!active) return;
          setPreviewDrawer((current) => current ? {
            ...current,
            samples: page.items.map((item) => ({ sample_id: item.sample_id, row_index: item.row_index, values: item.values })),
            sampleCursor: page.next_cursor,
            sampleTotal: page.total,
          } : current);
        }
      } catch (error) {
        if (active) setPreviewDrawer((current) => current ? { ...current, errorMessage: formatApiError(error, "预览状态加载失败") } : current);
      }
    };
    void refresh();
    timer = setInterval(() => { void refresh(); }, 1000);
    return () => { active = false; if (timer) clearInterval(timer); };
  }, [previewDrawer?.previewId, previewDrawer?.taskId]);

  useEffect(() => {
    if (!genericDiscoveryPreviewId || !genericDiscoveryTask || genericFinalStage) return;
    const taskId = genericDiscoveryTask.id;
    const previewId = genericDiscoveryPreviewId;
    let active = true;
    let timer: ReturnType<typeof setInterval> | undefined;
    const refresh = async () => {
      try {
        const preview = await getAnnotationPreview(taskId, previewId);
        if (!active) return;
        setGenericDiscoveryTask((current) => current ? { ...current, preview: { ...preview, id: previewId } } : current);
        const previewStatus = String(preview.status);
        if (["completed", "ready"].includes(previewStatus)) {
          if (timer) clearInterval(timer);
        } else if (["failed", "cancelled"].includes(previewStatus)) {
          if (timer) clearInterval(timer);
          setGenericDiscoveryError(preview.error_code || preview.error?.message || copy.clusterPreviewFailed);
        }
      } catch (error) {
        if (active) setGenericDiscoveryError(formatApiError(error, copy.clusterPreviewFailed));
      }
    };
    void refresh();
    timer = setInterval(() => { void refresh(); }, 1000);
    return () => { active = false; if (timer) clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [genericDiscoveryPreviewId, genericDiscoveryTask?.id, genericFinalStage]);

  useEffect(() => {
    if (!genericFinalStage || !genericFinalPreviewId || !genericDiscoveryTask) return;
    const taskId = genericDiscoveryTask.id;
    const previewId = genericFinalPreviewId;
    let active = true;
    let timer: ReturnType<typeof setInterval> | undefined;
    const refresh = async () => {
      try {
        const preview = await getAnnotationPreview(taskId, previewId);
        if (!active) return;
        setGenericDiscoveryTask((current) => current && current.task_revision === preview.task_revision
          ? { ...current, preview: { ...preview, id: previewId } } : current);
        const previewStatus = String(preview.status);
        if (["completed", "ready"].includes(previewStatus)) {
          if (timer) clearInterval(timer);
          const page = await listAnnotationPreviewSamples(taskId, previewId, 50);
          if (active) {
            setGenericFinalSamples(page);
            setGenericFinalPreviewError(null);
          }
        } else if (["failed", "cancelled"].includes(previewStatus)) {
          if (timer) clearInterval(timer);
          setGenericFinalPreviewError(preview.error_code || preview.error?.message || "最终预览生成失败");
        }
      } catch (error) {
        if (active) setGenericFinalPreviewError(formatApiError(error, "最终预览状态加载失败"));
      }
    };
    void refresh();
    timer = setInterval(() => { void refresh(); }, 1000);
    return () => { active = false; if (timer) clearInterval(timer); };
  }, [genericFinalPreviewId, genericDiscoveryTask?.id, genericFinalAttempt, genericFinalStage]);

  const openTaskPreview = async (task: AnnotationTask) => {
    const configHash = String(task.task_snapshot?.config_hash || "sha256:task");
    try {
      const existing = task.preview && task.preview.task_revision === task.task_revision
        && !["failed", "cancelled"].includes(task.preview.status)
        ? task.preview
        : null;
      const preview = existing
        ? { preview_id: existing.id, operation_id: existing.operation_id || undefined, task_revision: existing.task_revision, status: existing.status, dispatch_id: null }
        : await createAnnotationPreview(task.id, task.task_revision, configHash);
      setPreviewDrawer({
        snapshot: task.task_snapshot,
        taskId: task.id,
        previewId: preview.preview_id,
        operationId: preview.operation_id,
        taskRevision: preview.task_revision,
        status: preview.status,
        progress: 0,
        summary: { status: preview.status, dispatch_id: preview.dispatch_id || null, task_revision: preview.task_revision },
        samples: [],
        sampleCursor: null,
      });
    } catch (error) {
      if (isRevisionConflict(error)) setRevisionConflict(revisionConflictFromError(error, task));
      else message.error(formatApiError(error, "任务预览失败"));
    }
  };

  const openAssignmentDialog = async (task: AnnotationTask) => {
    setAssignmentTask(task);
    setAssignmentOverlapWarning(null);
    setAssignmentLoading(true);
    try {
      setAnnotators(await listAnnotatorSubjects());
    } catch (error) {
      message.error(formatApiError(error, "标注员加载失败"));
      setAnnotators([]);
    } finally {
      setAssignmentLoading(false);
    }
  };

  const sampleScopeForTask = (task: AnnotationTask): SampleScope => {
    const scope = task.sample_scope || {};
    if (scope.kind === "all" || scope.kind === "filter") {
      return { kind: "frozen_task_scope" };
    }
    const sampleIds = Array.isArray(scope.sample_ids) ? scope.sample_ids.map(String) : [];
    return { kind: "ids", sample_ids: sampleIds };
  };

  const submitAssignment = async (payload: { annotator_ids: string[]; sample_scope: SampleScope; due_at?: string }) => {
    if (!assignmentTask) return;
    setAssignmentLoading(true);
    try {
      const result = await createAssignments(assignmentTask.id, payload);
      setAssignmentOverlapWarning(result.overlap_warning || null);
      if (!result.overlap_warning) {
        message.success("指派已提交");
        setAssignmentTask(null);
      }
    } catch (error) {
      if (isRevisionConflict(error)) setRevisionConflict(revisionConflictFromError(error, assignmentTask));
      else message.error(formatApiError(error, "指派失败"));
    } finally {
      setAssignmentLoading(false);
    }
  };

  const executeGenericTask = async (task: AnnotationTask) => {
    try {
      const updated = await transitionAnnotationTask(task.id, task.task_revision, "execute", task.preview?.id);
      setGenericTasks((items) => items.map((item) => item.id === task.id ? { ...item, ...updated } : item));
      await refreshGenericTaskData();
    } catch (error) {
      if (isRevisionConflict(error)) setRevisionConflict(revisionConflictFromError(error, task));
      else message.error(formatApiError(error, "任务执行失败"));
    }
  };

  const clusterOptionsForTask = (task: AnnotationTask): ClusterOption[] => {
    const rawClusters = task.preview?.summary?.clusters;
    return Array.isArray(rawClusters) ? rawClusters.flatMap((cluster) => {
      if (!cluster || typeof cluster !== "object") return [];
      const item = cluster as Record<string, unknown>;
      const clusterId = item.cluster_id;
      const sampleCount = Number(item.sample_count);
      return clusterId !== undefined && Number.isFinite(sampleCount)
        ? [{ clusterId: String(clusterId), sampleCount }]
        : [];
    }) : [];
  };

  const clusterEvaluationForTask = (task: AnnotationTask): ClusterEvaluation | null => {
    const raw = task.preview?.summary?.cluster_evaluation;
    return raw && typeof raw === "object" ? raw as ClusterEvaluation : null;
  };

  const openAutomaticConfiguration = (task: AnnotationTask) => {
    const columns = outputColumnsFromSnapshot(task);
    if (!columns.length) {
      message.error("任务没有可配置的冻结标签合同");
      return;
    }
    setAutomaticConfigTask(task);
    setAutomaticConfigDraft(strategyDraftFromTask(task, columns));
  };

  const saveAutomaticConfiguration = async () => {
    if (!automaticConfigTask || automaticConfigSaving) return;
    const columns = outputColumnsFromSnapshot(automaticConfigTask);
    const configuration = automaticConfigurationFromDraft(
      automaticConfigDraft,
      columns,
      sourceColumnsFromSnapshot(automaticConfigTask),
      true,
      false,
    );
    if (configuration.error || !configuration.configuration) {
      message.error(configuration.error || "自动标注策略配置无效");
      return;
    }
    const snapshot = automaticConfigTask.task_snapshot || {};
    const visibleColumns = Array.isArray(snapshot.visible_columns) ? snapshot.visible_columns.map(String) : [];
    setAutomaticConfigSaving(true);
    try {
      const updated = await updateGenericAnnotationTaskConfiguration(automaticConfigTask.id, {
        task_revision: automaticConfigTask.task_revision,
        visible_columns: visibleColumns,
        instructions: String(snapshot.instructions || ""),
        configuration: configuration.configuration,
      });
      setGenericTasks((items) => items.map((item) => item.id === updated.id ? { ...item, ...updated } : item));
      setAutomaticConfigTask(null);
      message.success("自动标注策略已保存，请重新生成预览");
    } catch (error) {
      if (isRevisionConflict(error)) setRevisionConflict(revisionConflictFromError(error, automaticConfigTask));
      else message.error(formatApiError(error, "自动标注策略保存失败"));
    } finally {
      setAutomaticConfigSaving(false);
    }
  };

  const refreshGenericTaskData = async () => {
    if (!isTaskList || !projectId) return;
    try {
      const [tasks, operations] = await Promise.all([
        listAnnotationTasks(projectId),
        listAnnotationOperations(projectId),
      ]);
      setGenericTasks(tasks.items || []);
      setGenericTasksCursor(tasks.next_cursor || null);
      setAnnotationOperations(operations.items || []);
      setAnnotationOperationsCursor(operations.next_cursor || null);
    } catch (error) {
      message.error(formatApiError(error, "通用任务刷新失败"));
    }
  };

  const loadMoreAnnotationOperations = async () => {
    if (!projectId || !annotationOperationsCursor || operationsLoading) return;
    setOperationsLoading(true);
    try {
      const page = await listAnnotationOperations(projectId, 50, annotationOperationsCursor);
      setAnnotationOperations((items) => [...items, ...(page.items || [])]);
      setAnnotationOperationsCursor(page.next_cursor || null);
    } catch (error) {
      message.error(formatApiError(error, "更多通用操作加载失败"));
    } finally {
      setOperationsLoading(false);
    }
  };

  const loadExecutionView = async (operation: AnnotationOperation, statsKind: ExecutionStatsKind = "sample", append = false) => {
    const current = executionView?.operation.id === operation.id ? executionView : null;
    setExecutionView((value) => value && value.operation.id === operation.id ? { ...value, loading: true, error: null } : {
      operation, results: [], resultsCursor: null, statsKind, stats: [], statsCursor: null, loading: true, error: null,
    });
    try {
      const resultCursor = append ? current?.resultsCursor || undefined : undefined;
      const statsCursor = append && current?.statsKind === statsKind ? current.statsCursor || undefined : undefined;
      const [results, stats] = await Promise.all([
        append && !current?.resultsCursor ? null : listAnnotationExecutionResults(operation.task_id, operation.id, 50, resultCursor),
        append && current?.statsKind === statsKind && !current.statsCursor ? null : listAnnotationExecutionStats(operation.task_id, operation.id, statsKind, 50, statsCursor),
      ]);
      setExecutionView((value) => value && value.operation.id === operation.id ? {
        ...value,
        statsKind,
        results: results ? (append ? [...value.results, ...results.items] : results.items) : value.results,
        resultsCursor: results ? results.next_cursor : value.resultsCursor,
        stats: stats ? (append && value.statsKind === statsKind ? [...value.stats, ...stats.items] : stats.items) : value.stats,
        statsCursor: stats ? stats.next_cursor : value.statsCursor,
        loading: false,
        error: null,
      } : value);
    } catch (error) {
      const rendered = formatApiError(error, "执行结果加载失败");
      setExecutionView((value) => value && value.operation.id === operation.id ? { ...value, loading: false, error: rendered } : value);
      message.error(rendered);
    }
  };

  const transitionGenericTask = async (
    task: AnnotationTask,
    action: "publish" | "pause" | "resume" | "cancel" | "return" | "accept" | "complete" | "archive" | "restore" | "reopen",
  ) => {
    try {
      await transitionAnnotationTask(task.id, task.task_revision, action);
      await refreshGenericTaskData();
    } catch (error) {
      if (isRevisionConflict(error)) setRevisionConflict(revisionConflictFromError(error, task));
      else message.error(formatApiError(error, "任务状态更新失败"));
    }
  };

  const openEditConfiguration = (task: AnnotationTask) => {
    setEditConfigTask(task);
    setEditConfigDraft({
      name: task.name || "",
      instructions: String(task.task_snapshot?.instructions || ""),
      completionCriteria: String(task.completion_criteria ?? task.task_snapshot?.completion_criteria ?? ""),
      dueAt: task.due_at ? String(task.due_at).slice(0, 10) : "",
      visibleColumns: Array.isArray(task.task_snapshot?.visible_columns) ? task.task_snapshot.visible_columns.map(String) : [],
    });
  };

  const saveEditConfiguration = async () => {
    if (!editConfigTask || editConfigSaving) return;
    if (!editConfigDraft.name.trim()) {
      message.error(copy.nameRequired);
      return;
    }
    if (!editConfigDraft.visibleColumns.length) {
      message.error(lang === "zh" ? "请至少选择一个可见字段" : "Select at least one visible field");
      return;
    }
    setEditConfigSaving(true);
    try {
      const updated = await updateGenericAnnotationTaskConfiguration(editConfigTask.id, {
        task_revision: editConfigTask.task_revision,
        name: editConfigDraft.name.trim(),
        visible_columns: editConfigDraft.visibleColumns,
        instructions: editConfigDraft.instructions,
        completion_criteria: editConfigDraft.completionCriteria,
        due_at: editConfigDraft.dueAt ? new Date(`${editConfigDraft.dueAt}T23:59:59`).toISOString() : null,
        configuration: (editConfigTask.task_snapshot?.configuration as Record<string, unknown>) || {},
      });
      setGenericTasks((items) => items.map((item) => item.id === updated.id ? { ...item, ...updated } : item));
      message.success(copy.configurationSaved);
      setEditConfigTask(null);
    } catch (error) {
      if (isRevisionConflict(error)) setRevisionConflict(revisionConflictFromError(error, editConfigTask));
      else message.error(formatApiError(error, lang === "zh" ? "任务配置保存失败" : "Unable to save task configuration"));
    } finally {
      setEditConfigSaving(false);
    }
  };

  const retryTaskPreview = async (task: AnnotationTask) => {
    await openTaskPreview(task);
  };

  const loadMorePreviewSamples = async () => {
    if (!previewDrawer?.previewId || !previewDrawer.sampleCursor || previewDrawer.loading) return;
    const previewId = previewDrawer.previewId;
    setPreviewDrawer((current) => current ? { ...current, loading: true } : current);
    try {
      const page = await listAnnotationPreviewSamples(previewDrawer.taskId, previewDrawer.previewId, 50, previewDrawer.sampleCursor);
      setPreviewDrawer((current) => current?.previewId === previewId ? {
        ...current,
        samples: [...current.samples, ...page.items.map((item) => ({ sample_id: item.sample_id, row_index: item.row_index, values: item.values }))],
        sampleCursor: page.next_cursor,
        sampleTotal: page.total,
      } : current);
    } catch (error) {
      message.error(formatApiError(error, "预览样本加载失败"));
    } finally {
      setPreviewDrawer((current) => current?.previewId === previewId ? { ...current, loading: false } : current);
    }
  };

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
    setGenericVersions([]);
    setGenericVersionId("");
    if (!isSetup || !genericSetupMode || loadingProjects || !projectId) {
      return;
    }
    let active = true;
    listDatasetVersions(projectId)
      .then((items) => { if (active) setGenericVersions(items); })
      .catch((error) => { if (active) message.error(formatApiError(error, "数据版本加载失败")); });
    return () => { active = false; };
  }, [isSetup, genericSetupMode, loadingProjects, projectId, message]);

  useEffect(() => {
    const version = genericVersions.find((item) => item.id === genericVersionId);
    setGenericVisibleColumns(version ? version.columns.map((column) => column.name) : []);
    setGenericScopeMode("all");
    setGenericScopeConditions([]);
  }, [genericVersionId, genericVersions]);

  useEffect(() => {
    setGenericModelVersions([]);
    setGenericModelVersionId("");
    if (!isSetup || !genericSetupMode || labelMode !== "automatic" || loadingProjects || !projectId) {
      return;
    }
    let active = true;
    listAnnotationModelVersions(projectId)
      .then((items) => { if (active) setGenericModelVersions(items); })
      .catch((error) => { if (active) message.error(formatApiError(error, "可用模型版本加载失败")); });
    return () => { active = false; };
  }, [isSetup, genericSetupMode, labelMode, loadingProjects, projectId, message]);

  useEffect(() => {
    setGenericAutomaticDraft(createAutomaticStrategyDraft(effectiveAutoColumns));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedGenericModelVersion?.id, genericAutoSchema?.id]);

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
    kind: "condition",
    label: "",
    tokens: [{ kind: "data", value: "" }, { kind: "logical_operator", value: ">" }, { kind: "number", value: "" }],
  }]);

  const serializedAnnotationRules = (): AnnotationProcessRule[] => annotationRules.map((rule) => ({
    id: rule.id,
    kind: rule.kind || "condition",
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
      const validTokens = rule.kind === "fallback" ? rule.tokens.length === 0 : rule.tokens.length >= 3
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

  const saveLabelSchema = async (columns: LabelColumnDraft[], purpose: "annotation" | "training" | "inference") => {
    if (!projectId) { message.error("请先选择项目"); return; }
    try {
      const schema = await createLabelSchema(projectId, `${targetColumn.trim() || "labels"}-schema`, columns, purpose);
      setLabelSchemaId(schema.id);
      message.success(`标签 schema v${schema.version} 已保存`);
    } catch (error) {
      message.error(formatApiError(error, "标签 schema 保存失败"));
    }
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
    setGenericSetupMode(true);
    setRunId("");
    setLabelMode(nextMode);
    setGenericVersionId("");
    setGenericSchemaName("labels");
    setGenericLabelKey("label");
    setGenericLabelType("string");
    setGenericInstructions("");
    setGenericModelVersionId("");
    setGenericClustering(false);
    setGenericAutomaticDraft(createAutomaticStrategyDraft([]));
    setGenericDiscoveryTask(null);
    setGenericDiscoveryPreviewId(null);
    setGenericDiscoveryError(null);
    setGenericFinalPreviewId(null);
    setGenericFinalPreviewError(null);
    setGenericFinalStage(false);
    setGenericFinalSamples(null);
    setGenericSetupStep(1);
    setAutomaticSetupStep(1);
    setSearchParams((current) => {
      current.delete("type");
      current.set("view", "setup");
      current.set("mode", nextMode);
      current.delete("runId");
      return current;
    }, { replace: true });
  };

  const buildGenericSampleScope = (): { kind: "all" | "filter"; filters?: Record<string, unknown> } => {
    if (genericScopeMode !== "filter") return { kind: "all" };
    const version = genericVersions.find((item) => item.id === genericVersionId);
    const numericColumns = new Set((version?.columns || []).filter((column) => ["int", "float", "int64", "float64", "number"].includes(String(column.dtype).toLowerCase())).map((column) => column.name));
    // Every condition row must survive into the frozen scope; a column-keyed
    // map silently dropped same-column conditions (e.g. ranges) and leaked the
    // samples the user meant to exclude into the task.
    const conditions: Array<Record<string, Record<string, unknown>>> = [];
    for (const condition of genericScopeConditions) {
      const column = condition.column.trim();
      if (!column) continue;
      if (condition.operator === "is_null" || condition.operator === "not_null") {
        conditions.push({ [column]: { [condition.operator]: true } });
        continue;
      }
      if (!condition.value.trim()) continue;
      const raw = condition.value.trim();
      const numeric = Number(raw);
      conditions.push({ [column]: { [condition.operator]: numericColumns.has(column) && Number.isFinite(numeric) ? numeric : raw } });
    }
    return conditions.length ? { kind: "filter", filters: { all: conditions } } : { kind: "all" };
  };

  const resetGenericScopeDraft = () => {
    setGenericScopeMode("all");
    setGenericScopeConditions([]);
  };

  const saveGenericAutoSchema = async (columns: LabelColumnDraft[]) => {
    if (!projectId) { message.error(lang === "zh" ? "请先选择项目" : "Select a project first"); return; }
    if (!genericTaskName.trim()) { message.error(copy.nameRequired); return; }
    try {
      const schema = await createLabelSchema(projectId, `${genericTaskName.trim()}-labels`, columns, "annotation");
      setGenericAutoSchema({
        id: schema.id,
        columns: columns.map((column) => ({
          machine_key: column.machine_key,
          display_name: column.display_name,
          value_type: column.value_type,
          required: column.required,
        })),
      });
      message.success(lang === "zh" ? "自定义标签 schema 已保存" : "Custom label schema saved");
    } catch (error) {
      message.error(formatApiError(error, lang === "zh" ? "标签 schema 保存失败" : "Failed to save the label schema"));
    }
  };

  const createGenericTaskFromSetup = async () => {
    if (!projectId || !genericVersionId) return;
    const version = genericVersions.find((item) => item.id === genericVersionId && item.project_id === projectId);
    if (!version || genericCreating) return;
    if (!genericTaskName.trim()) {
      message.error(copy.nameRequired);
      return;
    }
    if (labelMode === "manual" && (!genericSchemaName.trim() || !genericLabelKey.trim())) return;
    if (labelMode === "automatic" && !selectedGenericModelVersion) {
      message.error("自动任务需要选择已启用模型版本");
      return;
    }
    if (labelMode === "automatic" && genericClustering && genericAutoLabelSource === "custom" && !genericAutoSchema) {
      message.error(lang === "zh" ? "自定义标签模式需要先保存标签 schema" : "Save the custom label schema first");
      return;
    }
    if (labelMode === "automatic" && (!effectiveAutoColumns.length)) {
      message.error("自动任务需要可用的标签列");
      return;
    }
    const sampleScope = buildGenericSampleScope();
    if (sampleScope.kind === "all" && genericScopeMode === "filter") {
      message.error(lang === "zh" ? "请至少配置一条有效的样本筛选条件" : "Configure at least one valid sample filter condition");
      return;
    }
    if (!genericVisibleColumns.length) {
      message.error(lang === "zh" ? "请至少选择一个可见字段" : "Select at least one visible field");
      return;
    }
    const automaticConfiguration = labelMode === "automatic"
      ? automaticConfigurationFromDraft(
        genericAutomaticDraft,
        effectiveAutoColumns,
        version.columns.map((column) => ({ name: column.name, dtype: column.dtype })),
        genericClustering,
        genericClustering && genericAutomaticDraft.strategy !== "rule",
      )
      : null;
    if (automaticConfiguration?.error) {
      message.error(automaticConfiguration.error);
      return;
    }
    setGenericCreating(true);
    try {
      const schema = labelMode === "manual" ? await createLabelSchema(projectId, genericSchemaName.trim(), [{
        machine_key: genericLabelKey.trim(),
        display_name: genericLabelKey.trim(),
        value_type: genericLabelType,
        required: false,
        ...(genericSchemaInstruction.trim() ? { instruction: genericSchemaInstruction.trim() } : {}),
      }]) : null;
      const task = await createGenericAnnotationTask({
        project_id: projectId,
        dataset_version_id: genericVersionId,
        ...(schema || (labelMode === "automatic" && genericClustering && genericAutoLabelSource === "custom" && genericAutoSchema) ? { label_schema_id: (schema || genericAutoSchema!).id } : {}),
        ...(selectedGenericModelVersion && labelMode === "automatic" ? { model_version_id: selectedGenericModelVersion.id } : {}),
        name: genericTaskName.trim(),
        mode: labelMode,
        sample_scope: sampleScope,
        visible_columns: genericVisibleColumns,
        instructions: genericInstructions,
        completion_criteria: genericCompletionCriteria,
        due_at: genericDueAt ? new Date(`${genericDueAt}T23:59:59`).toISOString() : null,
        configuration: automaticConfiguration?.configuration || {},
      }, crypto.randomUUID());
      setGenericTasks((items) => [task, ...items.filter((item) => item.id !== task.id)]);
      resetGenericScopeDraft();
      if (labelMode === "automatic") {
        await startFinalPreview(task);
      } else {
        message.success("通用标注任务已创建");
        returnToTaskList();
      }
    } catch (error) {
      message.error(formatApiError(error, "通用标注任务创建失败"));
    } finally {
      setGenericCreating(false);
    }
  };

  const startGenericDiscovery = async () => {
    if (!projectId || !genericVersionId || genericCreating || genericDiscoveryTask) return;
    const version = genericVersions.find((item) => item.id === genericVersionId && item.project_id === projectId);
    if (!version) return;
    if (!genericTaskName.trim()) {
      message.error(copy.nameRequired);
      return;
    }
    if (!selectedGenericModelVersion) {
      message.error("自动任务需要选择已启用模型版本");
      return;
    }
    if (genericAutoLabelSource === "custom" && !genericAutoSchema) {
      message.error(lang === "zh" ? "自定义标签模式需要先保存标签 schema" : "Save the custom label schema first");
      return;
    }
    if (!genericVisibleColumns.length) {
      message.error(lang === "zh" ? "请至少选择一个可见字段" : "Select at least one visible field");
      return;
    }
    const sampleScope = buildGenericSampleScope();
    if (sampleScope.kind === "all" && genericScopeMode === "filter") {
      message.error(lang === "zh" ? "请至少配置一条有效的样本筛选条件" : "Configure at least one valid sample filter condition");
      return;
    }
    setGenericCreating(true);
    setGenericDiscoveryError(null);
    try {
      const task = await createGenericAnnotationTask({
        project_id: projectId,
        dataset_version_id: genericVersionId,
        model_version_id: selectedGenericModelVersion.id,
        ...(genericAutoLabelSource === "custom" && genericAutoSchema ? { label_schema_id: genericAutoSchema.id } : {}),
        name: genericTaskName.trim(),
        mode: "automatic",
        sample_scope: sampleScope,
        visible_columns: genericVisibleColumns,
        instructions: genericInstructions,
        completion_criteria: genericCompletionCriteria,
        due_at: genericDueAt ? new Date(`${genericDueAt}T23:59:59`).toISOString() : null,
        configuration: { clustering: true, cluster_discovery: true },
      }, crypto.randomUUID());
      setGenericDiscoveryTask(task);
      setGenericFinalPreviewId(null);
      setGenericFinalPreviewError(null);
      setGenericTasks((items) => [task, ...items.filter((item) => item.id !== task.id)]);
      const configHash = String(task.task_snapshot?.config_hash || "sha256:task");
      const preview = await createAnnotationPreview(task.id, task.task_revision, configHash);
      setGenericDiscoveryPreviewId(preview.preview_id);
    } catch (error) {
      setGenericDiscoveryError(formatApiError(error, copy.clusterPreviewFailed));
    } finally {
      setGenericCreating(false);
    }
  };

  const saveGenericStrategy = async () => {
    if (!genericDiscoveryTask || genericCreating) return;
    const version = genericVersions.find((item) => item.id === genericVersionId);
    const sourceColumns = (version?.columns || []).map((column) => ({ name: column.name, dtype: column.dtype }));
    const result = automaticConfigurationFromDraft(genericAutomaticDraft, effectiveAutoColumns, sourceColumns, true, false);
    if (result.error || !result.configuration) {
      message.error(result.error || "自动标注策略配置无效");
      return;
    }
    setGenericCreating(true);
    try {
      const updated = await updateGenericAnnotationTaskConfiguration(genericDiscoveryTask.id, {
        task_revision: genericDiscoveryTask.task_revision,
        name: genericTaskName.trim() || genericDiscoveryTask.name,
        visible_columns: genericVisibleColumns,
        instructions: genericInstructions,
        completion_criteria: genericCompletionCriteria,
        due_at: genericDueAt ? new Date(`${genericDueAt}T23:59:59`).toISOString() : null,
        configuration: result.configuration,
      });
      setGenericTasks((items) => [updated, ...items.filter((item) => item.id !== updated.id)]);
      await startFinalPreview(updated);
    } catch (error) {
      message.error(formatApiError(error, "自动标注策略保存失败"));
    } finally {
      setGenericCreating(false);
    }
  };

  const startFinalPreview = async (task: AnnotationTask) => {
    // Preserve the committed revision even if enqueueing the preview fails.
    setGenericFinalStage(true);
    setGenericDiscoveryPreviewId(null);
    setGenericDiscoveryTask({ ...task, preview: null });
    setGenericFinalPreviewId(null);
    setGenericFinalPreviewError(null);
    setGenericFinalSamples(null);
    try {
      const configHash = task.task_snapshot?.config_hash;
      if (typeof configHash !== "string" || !configHash) throw new Error("Missing frozen configuration hash");
      const preview = await createAnnotationPreview(task.id, task.task_revision, configHash);
      setGenericFinalPreviewId(preview.preview_id);
      setGenericFinalAttempt((value) => value + 1);
    } catch (error) {
      setGenericFinalPreviewError(formatApiError(error, "最终预览生成失败"));
    }
  };

  const genericFinalReady = Boolean(genericFinalStage && genericDiscoveryTask && genericFinalPreviewId
    && genericDiscoveryTask.preview?.id === genericFinalPreviewId
    && genericDiscoveryTask.preview?.task_revision === genericDiscoveryTask.task_revision
    && ["completed", "ready"].includes(String(genericDiscoveryTask.preview?.status))
    && genericDiscoveryTask.preview?.summary?.configuration_complete === true
    && Number(genericDiscoveryTask.preview?.summary?.needs_review_count || 0) === 0
    && genericFinalSamples && !genericFinalPreviewError);

  const confirmGenericExecution = async () => {
    if (!genericFinalReady || !genericDiscoveryTask || !genericFinalPreviewId || genericCreating) return;
    setGenericCreating(true);
    try {
      const updated = await transitionAnnotationTask(
        genericDiscoveryTask.id,
        genericDiscoveryTask.task_revision,
        "execute",
        genericFinalPreviewId,
      );
      setGenericTasks((items) => [updated, ...items.filter((item) => item.id !== updated.id)]);
      message.success("自动标注执行已确认");
      resetGenericScopeDraft();
      returnToTaskList();
    } catch (error) {
      message.error(formatApiError(error, "自动标注执行确认失败"));
    } finally {
      setGenericCreating(false);
    }
  };

  const loadMoreGenericFinalSamples = async () => {
    if (!genericDiscoveryTask || !genericFinalPreviewId || !genericFinalSamples?.next_cursor || genericCreating) return;
    try {
      const page = await listAnnotationPreviewSamples(
        genericDiscoveryTask.id,
        genericFinalPreviewId,
        50,
        genericFinalSamples.next_cursor,
      );
      setGenericFinalSamples((current) => current ? {
        ...page,
        items: [...current.items, ...page.items],
      } : page);
    } catch (error) {
      message.error(formatApiError(error, "加载最终预览样本失败"));
    }
  };

  const returnToTaskList = () => {
    setGenericFinalStage(false);
    setGenericFinalPreviewId(null);
    setGenericDiscoveryPreviewId(null);
    detailRequestId.current += 1;
    skipUrlStateSyncRef.current = true;
    setWorkspaceMode(false);
    setGenericSetupMode(false);
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
    { title: copy.modeStatus, key: "status", render: (_: unknown, run: QualityRun) => <Tag color={runStatusColor(run)}>{runStatusText(run, lang)}</Tag> },
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
        <div className="data-annotation__section-head">
          <h3>{copy.tasksSection}</h3>
        </div>
        {genericTasks.length > 0 && <div className="data-annotation__generic-tasks" role="region" aria-label={copy.genericTasks}>
          <Table<AnnotationTask>
            rowKey="id"
            size="small"
            loading={genericTaskLoading}
            dataSource={genericTasks}
            pagination={false}
            scroll={{ x: 1180 }}
            columns={[
              { title: lang === "zh" ? "任务" : "Task", dataIndex: "id", render: (id: string, task: AnnotationTask) => { const shortId = String(id || "").slice(0, 8); return <div className="table-primary-cell"><strong>{task.name?.trim() || shortId}</strong><span>{task.mode === "manual" ? copy.manual : copy.automatic} · {shortId}</span></div>; } },
              { title: lang === "zh" ? "状态" : "Status", dataIndex: "status", render: (value: string) => <Tag color={taskStatusColor(value)}>{taskStatusLabel(value, lang)}</Tag> },
              { title: copy.sampleCount, key: "samples", render: (_: unknown, task: AnnotationTask) => { const count = (task.task_snapshot?.scope as { sample_count?: number } | undefined)?.sample_count; return count === undefined || count === null ? "-" : `${count} ${copy.rows}`; } },
              { title: copy.createdAt, dataIndex: "created_at", render: (value: string | null) => value ? new Date(value).toLocaleString() : "-" },
              { title: copy.dueAt, dataIndex: "due_at", render: (value: string | null) => value ? new Date(value).toLocaleDateString() : "-" },
              { title: lang === "zh" ? "修订" : "Revision", dataIndex: "task_revision" },
              { title: copy.actions, key: "actions", align: "right" as const, render: (_: unknown, task: AnnotationTask) => <div className="table-row-actions">
                <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void openTaskPreview(task); }}>{lang === "zh" ? "预览" : "Preview"}</button>
                {["draft", "failed", "needs_review"].includes(task.status) && <button type="button" className="ant-btn ant-btn-sm" onClick={() => openEditConfiguration(task)}>{copy.editTask}</button>}
                {["draft", "failed"].includes(task.status) && <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void retryTaskPreview(task); }}>{copy.retryPreview}</button>}
                {task.mode === "automatic" && task.status === "needs_review" && <button type="button" className="ant-btn ant-btn-sm" onClick={() => openAutomaticConfiguration(task)}>{lang === "zh" ? "配置策略" : "Configure strategy"}</button>}
                <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void openAssignmentDialog(task); }}>{lang === "zh" ? "指派标注员" : "Assign"}</button>
                <button type="button" className="ant-btn ant-btn-sm" onClick={() => setCommentTaskId(task.id)}>{lang === "zh" ? "批注管理" : "Comments"}</button>
                <button type="button" className="ant-btn ant-btn-sm" disabled={task.status !== "preview_ready" || !task.preview || task.preview.task_revision !== task.task_revision || task.preview.status !== "completed" || task.preview.summary?.configuration_complete === false || Number(task.preview.summary?.needs_review_count || 0) > 0} onClick={() => { void executeGenericTask(task); }}>{lang === "zh" ? "执行" : "Execute"}</button>
                {task.status === "preview_ready" && <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void transitionGenericTask(task, "publish"); }}>{lang === "zh" ? "发布" : "Publish"}</button>}
                {["preview_ready", "executing", "awaiting_annotation", "in_progress", "awaiting_return"].includes(task.status) && <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void transitionGenericTask(task, "pause"); }}>{lang === "zh" ? "暂停" : "Pause"}</button>}
                {task.status === "paused" && <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void transitionGenericTask(task, "resume"); }}>{lang === "zh" ? "恢复" : "Resume"}</button>}
                {["draft", "preview_ready", "executing", "awaiting_annotation", "in_progress", "awaiting_return", "paused", "failed", "needs_review"].includes(task.status) && <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void transitionGenericTask(task, "cancel"); }}>{lang === "zh" ? "取消" : "Cancel"}</button>}
                {task.status === "awaiting_return" && <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void transitionGenericTask(task, "return"); }}>{lang === "zh" ? "提交回传" : "Return"}</button>}
                {task.status === "returned_pending_acceptance" && <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void transitionGenericTask(task, "accept"); }}>{lang === "zh" ? "验收" : "Accept"}</button>}
                {task.status === "accepted" && <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void transitionGenericTask(task, "complete"); }}>{lang === "zh" ? "完成" : "Complete"}</button>}
                {["accepted", "completed", "cancelled"].includes(task.status) && <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void transitionGenericTask(task, "archive"); }}>{lang === "zh" ? "归档" : "Archive"}</button>}
                {task.status === "completed" && <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void transitionGenericTask(task, "reopen"); }}>{lang === "zh" ? "重开" : "Reopen"}</button>}
                {task.status === "archived" && <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void transitionGenericTask(task, "restore"); }}>{lang === "zh" ? "恢复归档" : "Restore"}</button>}
                <DeleteConfirmation
                  label={`删除通用任务 ${task.id}`}
                  targetName={task.name?.trim() || String(task.id || "").slice(0, 8)}
                  onConfirm={() => {
                    void deleteAnnotationTask(task.id).then(() => {
                      setGenericTasks((items) => items.filter((item) => item.id !== task.id));
                      message.success("通用任务已删除");
                    }).catch((error) => message.error(formatApiError(error, "通用任务删除失败")));
                  }}
                />
              </div> },
            ]}
          />
          {genericTasksCursor && <div className="table-row-actions"><button type="button" className="ant-btn ant-btn-sm" onClick={() => { void loadMoreGenericTasks(); }} disabled={genericTaskLoading}>{copy.loadMoreTasks}</button></div>}
        </div>}
        {genericTasks.length === 0 && !genericTaskLoading && <Empty description={copy.noTasks} />}
        {runs.length > 0 && <div className="data-annotation__legacy-tasks">
          <div className="data-annotation__section-head">
            <h3>{copy.legacySection}</h3>
          </div>
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
        </div>}
      </div>
      {commentTaskId && <AnnotationCommentModerationPanel taskId={commentTaskId} open onClose={() => setCommentTaskId(null)} />}
      <div className="table-surface data-annotation__operations-surface" role="region" aria-label="通用任务操作">
        <div className="data-annotation__section-head">
          <h3>{copy.operationsSection}</h3>
          <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void refreshGenericTaskData(); }} disabled={operationsLoading}>{lang === "zh" ? "刷新操作" : "Refresh"}</button>
        </div>
        <Table<AnnotationOperation>
          rowKey="id"
          size="small"
          loading={operationsLoading}
          dataSource={annotationOperations}
          pagination={false}
          locale={{ emptyText: "暂无运行中的通用操作" }}
          columns={[
            { title: "操作", dataIndex: "id", render: (value: string) => <code>{value}</code> },
            { title: "类型", dataIndex: "resource_type" },
            { title: "阶段", dataIndex: "stage" },
            { title: "状态", dataIndex: "state", render: (value: string) => <Tag color={taskStatusColor(value)}>{taskStatusLabel(value, lang)}</Tag> },
            { title: "进度", dataIndex: "progress", render: (value: number) => `${value}%` },
            { title: "错误", dataIndex: "error_code", render: (value: string | null) => value || "-" },
            { title: "结果", key: "results", render: (_: unknown, operation: AnnotationOperation) => operation.resource_type === "annotation_execution" && operation.state === "completed"
              ? <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void loadExecutionView(operation); }}>查看结果</button>
              : "-" },
          ]}
        />
        {annotationOperationsCursor && <div className="table-row-actions"><button type="button" className="ant-btn ant-btn-sm" onClick={() => { void loadMoreAnnotationOperations(); }} disabled={operationsLoading}>加载更多操作</button></div>}
        {executionView && <div className="data-annotation__execution-view" role="region" aria-label="执行结果">
          <div className="data-annotation__section-head">
            <h3>{copy.executionResults}</h3>
          </div>
          <div className="table-row-actions">
            {(["sample", "cluster", "rule", "final_label"] as ExecutionStatsKind[]).map((kind) => <button key={kind} type="button" className="ant-btn ant-btn-sm" onClick={() => { void loadExecutionView(executionView.operation, kind); }} disabled={executionView.loading || executionView.statsKind === kind}>{kind}</button>)}
          </div>
          {executionView.error && <div role="alert">{executionView.error}</div>}
          <Table<ExecutionViewState["results"][number]> rowKey="id" size="small" loading={executionView.loading} dataSource={executionView.results} pagination={false} scroll={{ x: 700 }} columns={[
            { title: "样本", dataIndex: "sample_id" }, { title: "序号", dataIndex: "row_index" }, { title: "状态", dataIndex: "status", render: (value: string) => <Tag color={taskStatusColor(value)}>{taskStatusLabel(value, lang)}</Tag> },
            { title: "最终标签", dataIndex: "values", render: (value: unknown) => <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(value)}</pre> },
            { title: "来源", dataIndex: "provenance", render: (value: unknown) => <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(value)}</pre> },
          ]} />
          <Table<Record<string, unknown>> rowKey={(item) => String(item.key)} size="small" loading={executionView.loading} dataSource={executionView.stats} pagination={false} columns={executionView.statsKind === "sample" ? [
            { title: "样本", dataIndex: "sample_id", render: String }, { title: "序号", dataIndex: "row_index", render: String }, { title: "状态", dataIndex: "status", render: (value: string) => <Tag color={taskStatusColor(value)}>{taskStatusLabel(value, lang)}</Tag> },
          ] : [
            { title: "统计", dataIndex: "key", render: (value: unknown) => String(value) }, { title: "数量", dataIndex: "count", render: (value: unknown) => value == null ? "-" : String(value) },
          ]} />
          {(executionView.resultsCursor || executionView.statsCursor) && <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void loadExecutionView(executionView.operation, executionView.statsKind, true); }} disabled={executionView.loading}>加载更多结果</button>}
        </div>}
      </div>
      {projectId && <ReturnAcceptancePanel projectId={projectId} />}
      <PreviewDrawer
        open={Boolean(previewDrawer)}
        snapshot={previewDrawer?.snapshot}
        status={previewDrawer?.status}
        loading={previewDrawer?.loading}
        sampleTotal={previewDrawer?.sampleTotal}
        operationId={previewDrawer?.operationId}
        summary={previewDrawer?.summary}
        progress={previewDrawer?.progress}
        strategySummary={previewDrawer?.strategySummary}
        errorMessage={previewDrawer?.errorMessage}
        samples={previewDrawer?.samples}
        hasMore={Boolean(previewDrawer?.sampleCursor)}
        onLoadMore={() => { void loadMorePreviewSamples(); }}
        onClose={() => setPreviewDrawer(null)}
      />
      <Modal
        open={Boolean(automaticConfigTask)}
        title="配置自动标注策略"
        onCancel={() => setAutomaticConfigTask(null)}
        footer={[
          <button type="button" className="ant-btn" key="cancel" onClick={() => setAutomaticConfigTask(null)} disabled={automaticConfigSaving}>取消</button>,
          <button type="button" className="ant-btn ant-btn-primary" key="save" onClick={() => { void saveAutomaticConfiguration(); }} disabled={automaticConfigSaving}>{automaticConfigSaving ? "保存中..." : "保存策略"}</button>,
        ]}
        width={960}
      >
        {automaticConfigTask && <>
          {clusterOptionsForTask(automaticConfigTask).length > 0 && <div className="data-annotation__setup-field" style={{ marginBottom: 12 }}>
            <ClusterPreviewPanel
              clusters={clusterOptionsForTask(automaticConfigTask)}
              evaluation={clusterEvaluationForTask(automaticConfigTask)}
              lang={lang}
            />
          </div>}
          <AutomaticAnnotationStrategyEditor
            idPrefix={`automatic-task-${automaticConfigTask.id}`}
            columns={outputColumnsFromSnapshot(automaticConfigTask)}
            sourceColumns={sourceColumnsFromSnapshot(automaticConfigTask)}
            clusters={clusterOptionsForTask(automaticConfigTask)}
            value={automaticConfigDraft}
            onChange={setAutomaticConfigDraft}
          />
        </>}
      </Modal>
      <AssignmentDialog
        open={Boolean(assignmentTask)}
        taskRevision={assignmentTask?.task_revision || 0}
        sampleScope={assignmentTask ? sampleScopeForTask(assignmentTask) : { kind: "frozen_task_scope" }}
        annotators={annotators}
        overlapWarning={assignmentOverlapWarning}
        loading={assignmentLoading}
        onClose={() => setAssignmentTask(null)}
        onSubmit={(payload) => { void submitAssignment(payload); }}
      />
      <Modal
        open={Boolean(editConfigTask)}
        title={copy.editTask}
        onCancel={() => setEditConfigTask(null)}
        footer={[
          <button type="button" className="ant-btn" key="cancel" onClick={() => setEditConfigTask(null)} disabled={editConfigSaving}>{lang === "zh" ? "取消" : "Cancel"}</button>,
          <button type="button" className="ant-btn ant-btn-primary" key="save" onClick={() => { void saveEditConfiguration(); }} disabled={editConfigSaving}>{editConfigSaving ? copy.savingConfiguration : copy.saveConfiguration}</button>,
        ]}
      >
        {editConfigTask && <div className="data-annotation__setup" aria-label={copy.editTask}>
          <div className="data-annotation__setup-field">
            <label htmlFor="edit-task-name">{copy.taskName}</label>
            <input id="edit-task-name" aria-label={copy.taskName} value={editConfigDraft.name} onChange={(event) => setEditConfigDraft((current) => ({ ...current, name: event.target.value }))} />
          </div>
          <div className="data-annotation__setup-field">
            <label htmlFor="edit-task-instructions">{lang === "zh" ? "标注说明" : "Instructions"}</label>
            <textarea id="edit-task-instructions" aria-label={lang === "zh" ? "标注说明" : "Instructions"} rows={4} value={editConfigDraft.instructions} onChange={(event) => setEditConfigDraft((current) => ({ ...current, instructions: event.target.value }))} />
          </div>
          <div className="data-annotation__setup-field">
            <label htmlFor="edit-task-completion-criteria">{copy.completionCriteria}</label>
            <textarea id="edit-task-completion-criteria" aria-label={copy.completionCriteria} rows={3} value={editConfigDraft.completionCriteria} onChange={(event) => setEditConfigDraft((current) => ({ ...current, completionCriteria: event.target.value }))} />
          </div>
          <div className="data-annotation__setup-field">
            <label htmlFor="edit-task-due-at">{copy.dueAt}</label>
            <input id="edit-task-due-at" type="date" aria-label={copy.dueAt} value={editConfigDraft.dueAt} onChange={(event) => setEditConfigDraft((current) => ({ ...current, dueAt: event.target.value }))} />
          </div>
          <div className="data-annotation__setup-field">
            <label>{copy.visibleColumns}</label>
            <div className="data-annotation__output-contract" role="group" aria-label={copy.visibleColumns}>
              {(editConfigTask.task_snapshot?.dataset_version?.columns || []).map((column: { name: string; dtype?: string }) => <label key={column.name} className="data-annotation__visible-column">
                <input type="checkbox" aria-label={column.name} checked={editConfigDraft.visibleColumns.includes(column.name)} onChange={(event) => setEditConfigDraft((current) => ({ ...current, visibleColumns: event.target.checked ? [...current.visibleColumns, column.name] : current.visibleColumns.filter((name) => name !== column.name) }))} />
                {column.name} · {column.dtype || "string"}
              </label>)}
            </div>
          </div>
        </div>}
      </Modal>
      <Modal
        open={Boolean(revisionConflict)}
        title="版本冲突"
        onCancel={() => setRevisionConflict(null)}
        footer={null}
      >
        {revisionConflict && <div role="alertdialog" aria-label="版本冲突">
          <p>{revisionConflict.message}</p>
          {revisionConflict.currentRevision !== undefined && <p>服务端当前修订：{revisionConflict.currentRevision}</p>}
          {revisionConflict.labels && <pre>{JSON.stringify(revisionConflict.labels, null, 2)}</pre>}
          <button type="button" className="ant-btn ant-btn-primary" onClick={() => setRevisionConflict(null)}>确认并覆盖完整标签</button>
        </div>}
      </Modal>
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
        {labelMode === "manual" && <div className="data-annotation__label-schema">
          <LabelSchemaEditor onSave={(columns, purpose) => void saveLabelSchema(columns, purpose)} />
          {labelSchemaId && <span>Schema ID: {labelSchemaId}</span>}
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
              <input id="annotation-weak-supervision-toggle" aria-label={copy.weakTitle} type="checkbox" checked={weakSupervision} onChange={(event) => {
                const enabled = event.target.checked;
                if (enabled) {
                  setAnnotationRules((current) => current.some((rule) => rule.kind === "fallback") ? current : [...current, {
                    id: `fallback-rule-${Date.now()}`,
                    kind: "fallback",
                    label: copy.fallbackLabel,
                    tokens: [],
                  }]);
                }
                setWeakSupervision(enabled);
                setClusterPreview(null);
              }} />
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
                <div className="data-annotation__annotation-rule-head"><strong>{copy.rule}</strong><Tooltip title={copy.deleteRule}><button type="button" className="ant-btn ant-btn-icon-only ant-btn-danger-icon" aria-label={lang === "zh" ? "删除" : `${copy.deleteRule} ${rule.id}`} onClick={() => removeAnnotationRule(rule.id)} disabled={annotationRules.length === 1 && rule.kind !== "fallback"}><DeleteOutlined /></button></Tooltip></div>
                {rule.kind === "fallback" ? <div className="data-annotation__rule-tokens"><span className="data-annotation__rule-token-value">{copy.fallbackCondition}</span></div> : <div className="data-annotation__rule-tokens">{rule.tokens.map((token, index) => {
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
                })}<button type="button" className="ant-btn ant-btn-sm" onClick={() => addAnnotationRuleToken(rule.id)}>{copy.addCondition}</button></div>}
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

  const modelIneligibleReasonText = (reason?: string | null) => {
    if (reason === "MODEL_SOURCE_UNSUPPORTED") return copy.modelIneligibleSourceUnsupported;
    if (reason === "MODEL_OUTPUT_CONTRACT_INVALID") return copy.modelIneligibleContractInvalid;
    return copy.modelIneligibleNotEnabled;
  };
  const genericSetupBasicsIncomplete = !canCreate || !genericTaskName.trim() || !genericVisibleColumns.length || !genericVersions.some((item) => item.id === genericVersionId && item.project_id === projectId) || (labelMode === "manual" ? (!genericSchemaName.trim() || !genericLabelKey.trim()) : !selectedGenericModelVersion);

  const genericSetupView = (
    <>
      <div className="page-header data-annotation__tasks-header">
        <div className="page-header-copy">
          <h2 className="page-title">{labelMode === "manual" ? "新建手动标注任务" : "新建自动标注任务"}</h2>
          <p className="page-subtitle">基于数据版本、标签 schema 和通用配置创建任务</p>
        </div>
        <button type="button" className="ant-btn" onClick={returnToTaskList}>{copy.backToTasks}</button>
      </div>
      <section className="data-annotation__setup" aria-label="通用任务创建">
        {labelMode === "automatic" && <Steps size="small" current={genericSetupStep - 1} items={[{ title: copy.setupStepBasics }, { title: copy.setupStepRules }]} />}
        {(labelMode === "manual" || genericSetupStep === 1) && <>
        <div className="data-annotation__setup-grid">
          <div className="data-annotation__setup-field">
            <label htmlFor="generic-task-name">{copy.taskName}</label>
            <input id="generic-task-name" aria-label={copy.taskName} value={genericTaskName} onChange={(event) => setGenericTaskName(event.target.value)} placeholder={copy.taskNamePlaceholder} maxLength={200} />
          </div>
          <div className="data-annotation__setup-field">
            <label htmlFor="generic-setup-project">{copy.project}</label>
            <select id="generic-setup-project" aria-label={copy.project} value={projectId} onChange={(event) => setProjectId(event.target.value)} disabled={loadingProjects}>
              <option value="">{copy.chooseProject}</option>
              {projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
            </select>
          </div>
          <div className="data-annotation__setup-field">
            <label htmlFor="generic-dataset-version">数据版本</label>
            <select id="generic-dataset-version" aria-label="数据版本" value={genericVersionId} onChange={(event) => setGenericVersionId(event.target.value)} disabled={!projectId || !genericVersions.length || !!genericDiscoveryTask}>
              <option value="">选择数据版本</option>
              {genericVersions.map((version) => <option value={version.id} key={version.id}>{version.source_name || `数据版本 v${version.version}`} · v{version.version} · {version.row_count} 行 · {version.columns.length} 列</option>)}
            </select>
          </div>
          {labelMode === "manual" && <>
            <div className="data-annotation__setup-field">
              <label htmlFor="generic-schema-name">标签 schema 名称</label>
              <input id="generic-schema-name" aria-label="标签 schema 名称" value={genericSchemaName} onChange={(event) => setGenericSchemaName(event.target.value)} />
            </div>
            <div className="data-annotation__setup-field">
              <label htmlFor="generic-label-key">标签字段</label>
              <input id="generic-label-key" aria-label="标签字段" value={genericLabelKey} onChange={(event) => setGenericLabelKey(event.target.value)} />
            </div>
            <div className="data-annotation__setup-field">
              <label htmlFor="generic-label-type">标签类型</label>
              <select id="generic-label-type" aria-label="标签类型" value={genericLabelType} onChange={(event) => setGenericLabelType(event.target.value as typeof genericLabelType)}>
                <option value="string">字符串</option>
                <option value="int">整数</option>
                <option value="float">浮点数</option>
              </select>
            </div>
            <div className="data-annotation__setup-field">
              <label htmlFor="generic-schema-instruction">{copy.schemaInstruction}</label>
              <input id="generic-schema-instruction" aria-label={copy.schemaInstruction} value={genericSchemaInstruction} onChange={(event) => setGenericSchemaInstruction(event.target.value)} placeholder={copy.schemaInstructionPlaceholder} />
            </div>
          </>}
          {labelMode === "automatic" && <>
            <div className="data-annotation__setup-field">
              <label htmlFor="generic-model-version">已启用模型版本</label>
              <select id="generic-model-version" aria-label="已启用模型版本" value={genericModelVersionId} onChange={(event) => setGenericModelVersionId(event.target.value)} disabled={!genericModelVersions.length || !!genericDiscoveryTask}>
                <option value="">{genericModelVersions.length === 0 ? copy.noModelVersions : "请选择模型版本"}</option>
                {genericModelVersions.map((modelVersion) => <option value={modelVersion.id} key={modelVersion.id} disabled={modelVersion.selectable === false}>{modelVersion.model_name} · v{modelVersion.version_number}{modelVersion.selectable === false ? ` · ${modelIneligibleReasonText(modelVersion.ineligible_reason)}` : ""}</option>)}
              </select>
            </div>
            {selectedGenericModelVersion && <div className="data-annotation__setup-field">
              <label>冻结标签合同</label>
              <div className="data-annotation__output-contract" aria-label="冻结标签合同">
                {selectedGenericOutputColumns.map((column) => <span key={column.machine_key}>{column.display_name} · {column.machine_key} · {column.value_type}</span>)}
              </div>
            </div>}
          </>}
        </div>
        <div className="data-annotation__setup-field">
          <label>{copy.sampleScope}</label>
          <div className="data-annotation__scope-mode" role="radiogroup" aria-label={copy.sampleScope}>
            <label><input type="radio" name="generic-scope-mode" checked={genericScopeMode === "all"} disabled={!!genericDiscoveryTask} onChange={() => setGenericScopeMode("all")} />{copy.scopeAll}</label>
            <label><input type="radio" name="generic-scope-mode" checked={genericScopeMode === "filter"} disabled={!!genericDiscoveryTask} onChange={() => setGenericScopeMode("filter")} />{copy.scopeFilter}</label>
          </div>
          {genericScopeMode === "filter" && <div className="data-annotation__scope-conditions">
            {genericScopeConditions.map((condition) => (
              <div className="data-annotation__scope-condition" key={condition.id}>
                <select aria-label={copy.scopeColumn} value={condition.column} onChange={(event) => setGenericScopeConditions((current) => current.map((item) => item.id === condition.id ? { ...item, column: event.target.value } : item))}>
                  <option value="">{copy.scopeColumn}</option>
                  {(genericVersions.find((item) => item.id === genericVersionId)?.columns || []).map((column) => <option value={column.name} key={column.name}>{column.name}</option>)}
                </select>
                <select aria-label={copy.scopeOperator} value={condition.operator} onChange={(event) => setGenericScopeConditions((current) => current.map((item) => item.id === condition.id ? { ...item, operator: event.target.value } : item))}>
                  {Object.entries(copy.operators).map(([key, text]) => <option value={key} key={key}>{text}</option>)}
                </select>
                <input aria-label={copy.scopeValue} value={condition.value} onChange={(event) => setGenericScopeConditions((current) => current.map((item) => item.id === condition.id ? { ...item, value: event.target.value } : item))} disabled={condition.operator === "is_null" || condition.operator === "not_null"} />
                <button type="button" className="ant-btn" aria-label={copy.removeScopeCondition} onClick={() => setGenericScopeConditions((current) => current.filter((item) => item.id !== condition.id))}>×</button>
              </div>
            ))}
            <button type="button" className="ant-btn" onClick={() => setGenericScopeConditions((current) => [...current, { id: crypto.randomUUID(), column: "", operator: "eq", value: "" }])}>{copy.addScopeCondition}</button>
            <small>{lang === "zh" ? "多个条件之间为 AND 关系" : "Conditions are combined with AND"}</small>
          </div>}
        </div>
        <div className="data-annotation__setup-field">
          <label>{copy.visibleColumns}</label>
          <div className="data-annotation__visible-columns" aria-label={copy.visibleColumns}>
            {(genericVersions.find((item) => item.id === genericVersionId)?.columns || []).map((column) => (
              <label key={column.name}><input type="checkbox" checked={genericVisibleColumns.includes(column.name)} onChange={(event) => setGenericVisibleColumns((current) => event.target.checked ? [...current, column.name] : current.filter((name) => name !== column.name))} />{column.name}</label>
            ))}
          </div>
        </div>
        <div className="data-annotation__setup-field">
          <label htmlFor="generic-instructions">标注说明</label>
          <textarea id="generic-instructions" aria-label="标注说明" value={genericInstructions} onChange={(event) => setGenericInstructions(event.target.value)} rows={4} />
        </div>
        <div className="data-annotation__setup-field">
          <label htmlFor="generic-completion-criteria">{copy.completionCriteria}</label>
          <textarea id="generic-completion-criteria" aria-label={copy.completionCriteria} value={genericCompletionCriteria} onChange={(event) => setGenericCompletionCriteria(event.target.value)} rows={3} placeholder={copy.completionCriteriaPlaceholder} />
        </div>
        <div className="data-annotation__setup-field">
          <label htmlFor="generic-due-at">{copy.dueAt}</label>
          <input id="generic-due-at" type="date" aria-label={copy.dueAt} value={genericDueAt} onChange={(event) => setGenericDueAt(event.target.value)} />
        </div>
        </>}
        {labelMode === "automatic" && genericSetupStep === 2 && <>
          <div className="data-annotation__setup-field">
            <label htmlFor="generic-weak-supervision">{copy.weakSupervision}</label>
            <select id="generic-weak-supervision" aria-label={copy.weakSupervision} value={genericClustering ? "yes" : "no"} disabled={!!genericDiscoveryTask} onChange={(event) => {
              const next = event.target.value === "yes";
              setGenericClustering(next);
              if (!next) setGenericAutoLabelSource("model");
            }}>
              <option value="no">{copy.weakSupervisionNo}</option>
              <option value="yes">{copy.weakSupervisionYes}</option>
            </select>
            <small>{genericClustering ? copy.clusteringOnHint : copy.clusteringOffHint}</small>
          </div>
          {genericClustering && !genericDiscoveryTask && <div className="data-annotation__setup-field" aria-label={lang === "zh" ? "标签来源" : "Label source"}>
            <label htmlFor="generic-auto-label-source">{lang === "zh" ? "标签来源" : "Label source"}</label>
            <select
              id="generic-auto-label-source"
              aria-label={lang === "zh" ? "标签来源" : "Label source"}
              value={genericAutoLabelSource}
              onChange={(event) => setGenericAutoLabelSource(event.target.value === "custom" ? "custom" : "model")}
              disabled={!!genericDiscoveryTask}
            >
              <option value="model">{lang === "zh" ? "模型输出合同（默认）" : "Model output contract (default)"}</option>
              <option value="custom">{lang === "zh" ? "用户指定标签列" : "User-specified label columns"}</option>
            </select>
            <small>{lang === "zh" ? "弱监督标注的最终标签由所选策略生成；可在此指定自己的标签列（簇/规则/兜底值都按这些列配置），模型输出仅作为内部来源保留。" : "Final labels come from the selected strategy; you may define your own label columns (cluster/rule/fallback values are configured against them) while model outputs stay an internal source."}</small>
          </div>}
          {genericClustering && !genericDiscoveryTask && genericAutoLabelSource === "custom" && <div className="data-annotation__setup-field" aria-label={lang === "zh" ? "自定义标签 schema" : "Custom label schema"}>
            <LabelSchemaEditor initialColumns={genericAutoSchema?.columns.map((column) => ({
              machine_key: column.machine_key,
              display_name: column.display_name,
              value_type: column.value_type,
              required: column.required,
            })) || []} onSave={(columns) => { void saveGenericAutoSchema(columns); }} />
            {genericAutoSchema && <small>{lang === "zh" ? `已保存 schema（${genericAutoSchema.columns.length} 列），创建任务时将使用这些标签列。` : `Saved schema (${genericAutoSchema.columns.length} columns); the task will use these label columns.`}</small>}
          </div>}
          {genericFinalPreviewId && genericDiscoveryTask ? (
            <div className="data-annotation__setup-field" aria-label="最终预览">
              <label>最终预览</label>
              {!genericFinalPreviewError && !["completed", "ready"].includes(String(genericDiscoveryTask.preview?.status)) && <><Spin size="small" /><small>最终预览生成中...</small></>}
              {genericFinalPreviewError && <><p role="alert">{genericFinalPreviewError}</p><button type="button" className="ant-btn" onClick={() => {
                setGenericFinalPreviewError(null);
                const configHash = String(genericDiscoveryTask.task_snapshot?.config_hash || "sha256:task");
                void createAnnotationPreview(genericDiscoveryTask.id, genericDiscoveryTask.task_revision, configHash)
                  .then((preview) => {
                    setGenericFinalPreviewId(preview.preview_id);
                    setGenericFinalAttempt((value) => value + 1);
                  })
                  .catch((error) => setGenericFinalPreviewError(formatApiError(error, "最终预览生成失败")));
              }}>重试最终预览</button></>}
              {!genericFinalPreviewError && genericFinalReady && <small>最终标签预览已完成，请确认执行。</small>}
              {!genericFinalPreviewError && genericFinalSamples && (
                <div className="data-annotation__final-preview" aria-label="最终预览结果">
                  <strong>全量统计</strong>
                  <pre>{JSON.stringify(genericDiscoveryTask.preview?.summary || {}, null, 2)}</pre>
                  <strong>分页样本（{genericFinalSamples.items.length} / {genericFinalSamples.total}）</strong>
                  <div className="data-annotation__final-preview-samples">
                    {genericFinalSamples.items.map((sample) => (
                      <pre key={`${sample.sample_id}-${sample.row_index}`}>{JSON.stringify(sample.values, null, 2)}</pre>
                    ))}
                  </div>
                  {genericFinalSamples.next_cursor && <button type="button" className="ant-btn ant-btn-sm" onClick={() => void loadMoreGenericFinalSamples()} disabled={genericCreating}>加载更多预览样本</button>}
                </div>
              )}
            </div>
          ) : genericClustering && selectedGenericModelVersion && (genericDiscoveryTask ? (
            (!genericDiscoveryPreviewId || !["completed", "ready"].includes(String(genericDiscoveryTask.preview?.status))) && !genericDiscoveryError
              ? <div className="data-annotation__setup-field" aria-label="聚类预览">
                  <label>{copy.clusterPreviewTitle}</label>
                  <Spin size="small" />
                  <small>{copy.clusterPreviewRunning}</small>
                </div>
              : <>
                  {genericDiscoveryError && <div className="data-annotation__setup-field" aria-label="聚类预览失败">
                    <label>{copy.clusterPreviewTitle}</label>
                    <p role="alert">{genericDiscoveryError}</p>
                    <button type="button" className="ant-btn" onClick={() => {
                      setGenericDiscoveryError(null);
                      const configHash = String(genericDiscoveryTask.task_snapshot?.config_hash || "sha256:task");
                      void createAnnotationPreview(genericDiscoveryTask.id, genericDiscoveryTask.task_revision, configHash)
                        .then((preview) => setGenericDiscoveryPreviewId(preview.preview_id))
                        .catch((error) => setGenericDiscoveryError(formatApiError(error, copy.clusterPreviewFailed)));
                    }}>{copy.retryClusterPreview}</button>
                  </div>}
                  {!genericDiscoveryError && <div className="data-annotation__setup-field">
                    <ClusterPreviewPanel
                      clusters={clusterOptionsForTask(genericDiscoveryTask)}
                      evaluation={clusterEvaluationForTask(genericDiscoveryTask)}
                      lang={lang}
                    />
                    <AutomaticAnnotationStrategyEditor
                      idPrefix="generic-setup-automatic"
                      columns={effectiveAutoColumns}
                      sourceColumns={(genericVersions.find((item) => item.id === genericVersionId)?.columns || []).map((column) => ({ name: column.name, dtype: column.dtype }))}
                      clusters={clusterOptionsForTask(genericDiscoveryTask)}
                      value={genericAutomaticDraft}
                      onChange={setGenericAutomaticDraft}
                    />
                    <small>{copy.clusterPreviewReadyHint}</small>
                  </div>}
                </>
          ) : <div className="data-annotation__setup-field" aria-label="聚类预览">
              <label>{copy.clusterPreviewTitle}</label>
              <button type="button" className="ant-btn" onClick={() => void startGenericDiscovery()} disabled={genericSetupBasicsIncomplete || genericCreating}>
                {genericCreating ? copy.clusterPreviewRunning : copy.generateClusters}
              </button>
              <small>{copy.discoveryHint}</small>
            </div>)}
        </>}
        <div className="data-annotation__setup-footer data-annotation__setup-footer--centered">
          {labelMode === "automatic" && genericSetupStep === 2 && <button type="button" className="ant-btn" onClick={() => setGenericSetupStep(1)}>{copy.prevStep}</button>}
          {labelMode === "automatic" && genericSetupStep === 1
            ? <button type="button" className="ant-btn ant-btn-primary" onClick={() => setGenericSetupStep(2)} disabled={genericSetupBasicsIncomplete}>{copy.nextStep}</button>
            : labelMode === "automatic" && genericFinalPreviewId && genericDiscoveryTask
              ? <button type="button" className="ant-btn ant-btn-primary" onClick={() => void confirmGenericExecution()} disabled={!genericFinalReady || genericCreating}>
                  {genericCreating ? "确认中..." : "确认执行"}
                </button>
            : labelMode === "automatic" && genericClustering
              ? (genericDiscoveryTask
                  ? <button type="button" className="ant-btn ant-btn-primary" onClick={() => void saveGenericStrategy()} disabled={!genericDiscoveryPreviewId || !["completed", "ready"].includes(String(genericDiscoveryTask.preview?.status)) || genericCreating}>
                      {genericCreating ? "保存中..." : copy.saveStrategy}
                    </button>
                  : <button type="button" className="ant-btn ant-btn-primary" onClick={() => void startGenericDiscovery()} disabled={genericSetupBasicsIncomplete || genericCreating}>
                      {genericCreating ? copy.clusterPreviewRunning : copy.generateClusters}
                    </button>)
              : <button type="button" className="ant-btn ant-btn-primary" onClick={() => void createGenericTaskFromSetup()} disabled={genericSetupBasicsIncomplete || genericCreating}>
                  {genericCreating ? "创建中..." : "创建通用任务"}
                </button>}
        </div>
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
          <div className="spot-weld-annotation__region-head"><h3 id="spot-weld-detail-title">{copy.sampleDetail}</h3>{selectedRun && <Tag color={runStatusColor(selectedRun)}>{runStatusText(selectedRun, lang)}</Tag>}</div>
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
        {isTaskList ? (loadingProjects ? <div className="data-annotation__loading"><Spin /></div> : tasksView) : isSetup ? (loadingProjects || loadingDatasets ? <div className="data-annotation__loading"><Spin /></div> : genericSetupMode ? genericSetupView : setupView) : workspaceView}
      </div>
    </AppLayout>
  );
}
