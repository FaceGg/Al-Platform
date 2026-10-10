import apiClient from "./client";

export interface RoutingPolicy {
  id: string;
  project_id: string;
  priority: number;
  policy_json: Record<string, unknown>;
  revision: number;
}

export interface StorageBinding {
  id: string;
  cluster_id: string;
  mode: "pvc" | "object_prefix";
  pvc_name: string | null;
  object_prefix: string | null;
  access: "read_only" | "read_write";
  status: string;
}

export interface QuotaPolicy {
  id: string;
  scope: string;
  scope_id: string;
  quota_json: Record<string, number>;
  revision: number;
}

export interface Reservation {
  id: string;
  project_id: string;
  cluster_id: string;
  operation_id: string;
  reserved_json: Record<string, number>;
  state: string;
  release_reason: string | null;
}

export interface UsageSnapshot {
  id: string;
  cluster_id: string;
  scope: string;
  subject: string;
  metrics_json: Record<string, unknown>;
  truncated: boolean;
  collected_at: string | null;
}

export interface RoutingPreview {
  selected_cluster_id: string | null;
  reason: string;
  policy_revision: number | null;
  candidates: Array<{ cluster_id: string; name: string; excluded: boolean; reason: string | null }>;
}

export async function listRoutingPolicies(projectId: string): Promise<{ items: RoutingPolicy[] }> {
  const res = await apiClient.get("/cluster-governance/routing-policies", { params: { project_id: projectId } });
  return res.data;
}

export async function listStorageBindings(projectId: string): Promise<{ items: StorageBinding[] }> {
  const res = await apiClient.get("/cluster-governance/storage-bindings", { params: { project_id: projectId } });
  return res.data;
}

export async function listQuotaPolicies(): Promise<{ items: QuotaPolicy[] }> {
  const res = await apiClient.get("/cluster-governance/quota-policies");
  return res.data;
}

export async function listReservations(projectId: string): Promise<{ items: Reservation[] }> {
  const res = await apiClient.get("/cluster-governance/reservations", { params: { project_id: projectId } });
  return res.data;
}

export async function listUsage(
  projectId: string,
  scope?: string,
): Promise<{ items: UsageSnapshot[]; stale_by_cluster: Record<string, boolean> }> {
  const res = await apiClient.get("/cluster-governance/usage", {
    params: { project_id: projectId, ...(scope ? { scope } : {}) },
  });
  return res.data;
}

export async function routingPreview(
  projectId: string,
  cpuCores = 1,
  gpuCount = 0,
): Promise<RoutingPreview> {
  const res = await apiClient.get("/cluster-governance/routing/preview", {
    params: { project_id: projectId, cpu_cores: cpuCores, gpu_count: gpuCount },
  });
  return res.data;
}
