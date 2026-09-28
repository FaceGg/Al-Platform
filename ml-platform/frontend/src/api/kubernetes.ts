import apiClient from "./client";

export type ClusterStatus = "pending" | "active" | "connectivity_failed" | "disabled";

export interface ClusterInfo {
  id: string;
  project_id: string;
  name: string;
  display_name: string;
  api_server_url: string;
  insecure_tls: boolean;
  provider: string;
  kubernetes_version: string | null;
  default_namespace: string | null;
  status: ClusterStatus;
  last_check_status: string | null;
  last_check_error_code: string | null;
  last_check_message: string | null;
  last_checked_at: string | null;
  last_check_latency_ms: number | null;
  stale: boolean;
  secret_ref: string | null;
  created_at: string | null;
}

export interface NodeCapability {
  hostname: string;
  arch: string;
  cpu_cores: string;
  memory: string;
  gpu: string;
  labels: Record<string, string>;
}

export interface NamespaceInfo {
  id: string;
  cluster_id: string;
  project_id: string;
  name: string;
  status: string;
  quota_cpu_millicores: number | null;
  quota_memory_mb: number | null;
  quota_json: Record<string, number> | null;
  last_synced_at: string | null;
}

export interface ResourceGroupInfo {
  id: string;
  cluster_id: string;
  project_id: string;
  name: string;
  description: string;
  scheduling_policy_json: Record<string, unknown>;
  quota_json: Record<string, number>;
  status: string;
}

export interface ClusterCreateRequest {
  project_id: string;
  name: string;
  display_name?: string;
  api_server_url: string;
  secret_ref: string;
  insecure_tls?: boolean;
  provider?: string;
  default_namespace?: string | null;
}

export interface ConnectivityCheckResult {
  check_status: "ok" | "failed";
  error_code: string | null;
  latency_ms: number;
  checked_at: string | null;
  kubernetes_version?: string | null;
}

export async function listClusters(offset = 0, limit = 100): Promise<{ items: ClusterInfo[]; total: number }> {
  const res = await apiClient.get("/api/kubernetes/clusters", { params: { offset, limit } });
  return res.data;
}

export async function getCluster(clusterId: string): Promise<ClusterInfo> {
  const res = await apiClient.get(`/api/kubernetes/clusters/${clusterId}`);
  return res.data;
}

export async function createCluster(payload: ClusterCreateRequest): Promise<ClusterInfo> {
  const res = await apiClient.post("/api/kubernetes/clusters", payload);
  return res.data;
}

export async function updateCluster(
  clusterId: string,
  payload: Partial<Pick<ClusterCreateRequest, "display_name" | "api_server_url" | "secret_ref" | "insecure_tls" | "default_namespace">>,
): Promise<ClusterInfo> {
  const res = await apiClient.patch(`/api/kubernetes/clusters/${clusterId}`, payload);
  return res.data;
}

export async function deleteCluster(clusterId: string): Promise<void> {
  await apiClient.delete(`/api/kubernetes/clusters/${clusterId}`);
}

export async function runConnectivityCheck(clusterId: string): Promise<ConnectivityCheckResult> {
  const res = await apiClient.post(`/api/kubernetes/clusters/${clusterId}/connectivity-check`, {});
  return res.data;
}

export async function listClusterNodes(clusterId: string): Promise<{ items: NodeCapability[]; total: number }> {
  const res = await apiClient.get(`/api/kubernetes/clusters/${clusterId}/nodes`);
  return res.data;
}

export async function listClusterNamespaces(clusterId: string): Promise<{ items: string[]; total: number }> {
  const res = await apiClient.get(`/api/kubernetes/clusters/${clusterId}/namespaces`);
  return res.data;
}

export async function ensureNamespace(
  clusterId: string,
  name: string,
  quotaJson: Record<string, number> | null,
): Promise<NamespaceInfo> {
  const res = await apiClient.put(`/api/kubernetes/clusters/${clusterId}/namespaces/${name}`, {
    quota_json: quotaJson,
  });
  return res.data;
}

export async function listResourceGroups(clusterId?: string): Promise<{ items: ResourceGroupInfo[]; total: number }> {
  const res = await apiClient.get("/api/kubernetes/resource-groups", {
    params: clusterId ? { cluster_id: clusterId } : {},
  });
  return res.data;
}

export async function createResourceGroup(payload: {
  cluster_id: string;
  name: string;
  description?: string;
  quota_json?: Record<string, number>;
}): Promise<ResourceGroupInfo> {
  const res = await apiClient.post("/api/kubernetes/resource-groups", payload);
  return res.data;
}
