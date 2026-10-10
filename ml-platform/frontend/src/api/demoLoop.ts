import { apiDelete, apiGet, apiPost, apiPut } from "./client";

export interface DemoLoopDeployment {
  id: string;
  name: string;
  desired_state: string;
  observed_state: string;
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
  alert_threshold_rows: number;
  require_review: boolean;
  review_annotator_ids: string[];
  retrain_enabled: boolean;
  retrain_threshold_rows: number;
  retrain_dataset_artifact_id: string | null;
  retrain_dataset_artifact_ids: string[];
  retrain_target_column: string;
  retrain_max_trials: number;
  retrain_dataset: { id: string; name: string } | null;
  deployment: DemoLoopDeployment | null;
  current_model: DemoLoopModelInfo | null;
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
}

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

export const fetchDemoLoopConfig = (projectId: string) =>
  apiGet(`/projects/${projectId}/demo-loop/config`);

export const saveDemoLoopConfig = (
  projectId: string,
  payload: Partial<DemoLoopConfig>,
) => apiPut(`/projects/${projectId}/demo-loop/config`, payload);

export const predictDemoLoopRow = (projectId: string, record: Record<string, unknown>) =>
  apiPost(`/projects/${projectId}/demo-loop/predict`, { record });

export const fetchDemoLoopStatus = (projectId: string) =>
  apiGet(`/projects/${projectId}/demo-loop/status`);

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
