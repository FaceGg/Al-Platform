import { apiDelete, apiGet, apiPost, apiPut } from "./client";

export interface DemoLoopDeployment {
  id: string;
  name: string;
  desired_state: string;
  observed_state: string;
  target_columns?: string[];
}

export interface DemoLoopModelInfo {
  model_version_id: string;
  version_number: number;
  model_name: string | null;
  lifecycle_state: string;
  approval_status: string;
  feature_schema: string[];
}

export interface DemoLoopConfig {
  id: string;
  project_id: string;
  name: string;
  deployment_id: string | null;
  error_classes: string[];
  preprocess_enabled: boolean;
  feature_engineering_mode?: "legacy" | "operator" | "script";
  feature_operator_id?: string | null;
  feature_script?: string | null;
  alert_threshold_rows: number;
  require_review: boolean;
  review_annotator_ids: string[];
  retrain_enabled: boolean;
  retrain_threshold_rows: number;
  retrain_dataset_artifact_id: string | null;
  retrain_dataset_artifact_ids: string[];
  retrain_target_column: string;
  retrain_max_trials: number;
  /** 闭环重训终选层集成（多模型加权投票），仅单输出分类生效 */
  retrain_ensemble_enabled?: boolean;
  retrain_ensemble_top_k?: number;
  /** 重训模式：engine=引擎直接重训换模（默认）；agent=复用固化配方重放智能体全流程 */
  retrain_mode?: "engine" | "agent";
  retrain_agent_recipe_id?: string | null;
  retrain_agent_run_id?: string | null;
  retrain_cool_until?: string | null;
  retrain_trained_baseline_count?: number;
  /** 重训特征列白名单（稀疏宽表必配，空=全部数值列） */
  retrain_input_columns?: string[];
  collect_correct_enabled: boolean;
  correct_sample_ratio: string | null;
  field_descriptions: Record<string, string> | null;
  error_artifact_id: string | null;
  retrain_dataset: { id: string; name: string } | null;
  deployment: DemoLoopDeployment | null;
  current_model: (DemoLoopModelInfo & { target_columns?: string[] }) | null;
  swapped_model_version_id: string | null;
  error_count: number;
  alert_count: number;
  total_count: number;
  retrain_status: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface DemoLoopEvent {
  id: string;
  event_type: string;
  severity: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface DemoLoopStatus {
  config_id: string;
  error_count: number;
  alert_count: number;
  total_count: number;
  retrain_status: string;
  retrain_job_id: string | null;
  review_task_id: string | null;
  swapped_model_version_id: string | null;
  error_artifact: { id: string; name: string; row_count: number } | null;
  events: DemoLoopEvent[];
  /** 增量触发基线：已部署模型消费过的报错行数（进度与触发判据用） */
  retrain_trained_baseline_count?: number;
  retrain_mode?: "engine" | "agent";
  retrain_cool_until?: string | null;
  retrain_input_columns?: string[];
  /** 无监督漂移治理（技术方案 §3.6）：最近一次 PSI 评估结果 */
  psi_state?: { last_total?: number; psi?: number | null; level?: string; sample_count?: number; per_shard?: { condition_value: string | null; psi: number; level: string }[] } | null;
  psi_enabled?: boolean;
  psi_threshold?: number;
  /** 部署 id（机群分片概览面板拉取 fleet-overview 用，三期 M10） */
  deployment_id?: string | null;
}

export interface ReflowRow {
  row_index: number;
  record: Record<string, unknown>;
  anomaly_score: number | null;
  feedback: string;
}

/** 报警确认反馈（§3.6 弱监督回流）：回流行列表 + 行级标记 */
export const fetchReflowRows = (projectId: string, loopId: string, limit = 50) =>
  apiGet(`/projects/${projectId}/demo-loop/loops/${loopId}/reflow-rows?limit=${limit}`);

export const markReflowRow = (
  projectId: string,
  loopId: string,
  payload: { artifact_id: string; row_index: number; mark: "confirmed_fault" | "false_alarm" | "none" },
) => apiPost(`/projects/${projectId}/demo-loop/loops/${loopId}/reflow-rows/feedback`, payload);

export interface DemoLoopPredictResult {
  prediction: string;
  confidence: number | null;
  model_version_id: string;
  error_matched: boolean;
  appended: boolean;
  error_count: number;
  alert_count: number;
  retrain_status: string;
}

export const resetDemoLoop = (projectId: string) =>
  apiPost(`/projects/${projectId}/demo-loop/reset`, {});

// ------------------------------------------------------- loop task list (CRUD)

export const fetchDemoLoops = (projectId: string) =>
  apiGet(`/projects/${projectId}/demo-loop/loops`);

export const createDemoLoop = (
  projectId: string,
  payload: Partial<DemoLoopConfig>,
) => apiPost(`/projects/${projectId}/demo-loop/loops`, payload);

export const updateDemoLoop = (
  projectId: string,
  loopId: string,
  payload: Partial<DemoLoopConfig>,
) => apiPut(`/projects/${projectId}/demo-loop/loops/${loopId}`, payload);

export const deleteDemoLoop = (projectId: string, loopId: string) =>
  apiDelete(`/projects/${projectId}/demo-loop/loops/${loopId}`);

export const predictDemoLoopRowScoped = (
  projectId: string,
  loopId: string,
  record: Record<string, unknown>,
) => apiPost(`/projects/${projectId}/demo-loop/loops/${loopId}/predict`, { record });

export const fetchDemoLoopStatusScoped = (projectId: string, loopId: string) =>
  apiGet(`/projects/${projectId}/demo-loop/loops/${loopId}/status`);

export const resetDemoLoopScoped = (projectId: string, loopId: string) =>
  apiPost(`/projects/${projectId}/demo-loop/loops/${loopId}/reset`, {});

export const fetchDemoLoopProjects = () => apiGet("/projects");

export const fetchDemoLoopDeployments = (projectId: string) =>
  apiGet(`/projects/${projectId}/inference-deployments`);

export const fetchDemoLoopDatasets = (projectId: string) =>
  apiGet(`/projects/${projectId}/datasets`);

export const fetchDemoLoopAnnotators = (projectId: string) =>
  apiGet(`/annotators?project_id=${projectId}`);
