import apiClient from "./client";

/** 质量领域 API（补齐路线第一批 B1-10）：场景/工位/规格定义。 */

export type QualityFieldRole =
  | "sample_key"
  | "product"
  | "batch"
  | "shift"
  | "collected_at"
  | "time"
  | "group"
  | "target"
  | "feature"
  | "ignore"
  | "waveform"
  | "condition";

export interface QualityScene {
  id: string;
  project_id: string;
  code: string;
  name: string;
  description: string | null;
  deployment_id: string | null;
  condition_column: string | null;
  field_roles: Partial<Record<QualityFieldRole, string>>;
  waveform_column: string | null;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface QualityStation {
  id: string;
  scene_id: string;
  code: string;
  name: string;
  description: string | null;
  factory: string | null;
  workshop: string | null;
  production_line: string | null;
  edge_device_id: string | null;
  responsible_user_id: string | null;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface QualitySpecLimit {
  id: string;
  scene_id: string;
  field: string;
  statistic: "value" | "mean" | "min" | "max" | "rms";
  usl: number | null;
  lsl: number | null;
  target: number | null;
  unit: string | null;
}

export async function listQualityScenes(projectId: string): Promise<QualityScene[]> {
  const res = await apiClient.get(`/projects/${projectId}/quality-scenes`);
  return res.data?.items ?? [];
}

export async function listQualityStations(projectId: string, sceneId?: string): Promise<QualityStation[]> {
  const res = await apiClient.get(`/projects/${projectId}/quality-stations`, {
    params: sceneId ? { scene_id: sceneId } : undefined,
  });
  return res.data?.items ?? [];
}

export async function listQualitySpecLimits(projectId: string, sceneId: string): Promise<QualitySpecLimit[]> {
  const res = await apiClient.get(`/projects/${projectId}/quality-scenes/${sceneId}/spec-limits`);
  return res.data?.items ?? [];
}

/**
 * field_roles → 训练排除列（技术方案 §2.3）：ignore 角色与被非目标角色
 * 占用的列不进模型输入；target/feature 两角色不排除。
 */
export const FIELD_ROLE_EXCLUDED: ReadonlySet<QualityFieldRole> = new Set([
  "ignore",
  "sample_key",
  "product",
  "batch",
  "shift",
  "collected_at",
  "time",
  "group",
  "condition",
  "waveform",
]);

export function sceneExcludedColumns(scene: QualityScene | null | undefined): string[] {
  if (!scene?.field_roles) return [];
  return Object.entries(scene.field_roles)
    .filter(([role]) => FIELD_ROLE_EXCLUDED.has(role as QualityFieldRole))
    .map(([, column]) => column);
}
