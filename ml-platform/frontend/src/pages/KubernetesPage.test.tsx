import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import KubernetesPage from "./KubernetesPage";
import type { ClusterInfo } from "../api/kubernetes";

const mocks = vi.hoisted(() => ({
  listClusters: vi.fn(),
  listClusterNodes: vi.fn(),
  listClusterNamespaces: vi.fn(),
  listResourceGroups: vi.fn(),
  runConnectivityCheck: vi.fn(),
  createCluster: vi.fn(),
  deleteCluster: vi.fn(),
  ensureNamespace: vi.fn(),
  updateCluster: vi.fn(),
  createResourceGroup: vi.fn(),
  getCluster: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/kubernetes", () => mocks);
vi.mock("../api/client", () => ({
  default: { get: vi.fn().mockResolvedValue({ data: { items: [{ id: "p1", name: "Week 13 项目" }] } }) },
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      kubernetes: {
        title: "Kubernetes 集群", cluster: "集群", provider: "类型", status: "状态", version: "版本",
        lastCheck: "最近检查", credentialRef: "凭据引用", actions: "操作", check: "连通性检查",
        nodes: "节点能力", namespaces: "命名空间", resourceGroups: "资源组", offline: "下线",
        stale: "检查结果已过期", neverChecked: "未检查", register: "登记集群", refresh: "刷新",
        selectProject: "选择项目", name: "标识名", empty: "尚无登记集群",
        hint: "凭据只保存 env:/file: 引用;端点必须在 allowlist 内。",
        checkOk: "连通性正常", checkFailed: "连通性检查失败", deleteConfirm: "确认下线该集群?",
      },
      common: { save: "保存", cancel: "取消" },
    },
  }),
}));

function renderPage() {
  return render(
    <AntApp>
      <KubernetesPage />
    </AntApp>,
  );
}

function makeCluster(overrides: Partial<ClusterInfo> = {}): ClusterInfo {
  return {
    id: "c1",
    project_id: "p1",
    name: "w13-kind",
    display_name: "Week 13 kind",
    api_server_url: "https://127.0.0.1:6443",
    insecure_tls: false,
    provider: "kind",
    kubernetes_version: "v1.30.0",
    default_namespace: null,
    status: "active",
    last_check_status: "ok",
    last_check_error_code: null,
    last_check_message: null,
    last_checked_at: new Date().toISOString(),
    last_check_latency_ms: 12,
    stale: false,
    secret_ref: "env:LINKRAFT_KIND_TOKEN",
    created_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listClusters.mockResolvedValue({ items: [makeCluster()], total: 1 });
});

describe("KubernetesPage", () => {
  it("renders registered clusters with status and credential reference", async () => {
    renderPage();
    expect(await screen.findByText("Week 13 kind")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByText("env:LINKRAFT_KIND_TOKEN")).toBeInTheDocument();
  });

  it("shows the stale marker for outdated check results", async () => {
    mocks.listClusters.mockResolvedValue({ items: [makeCluster({ stale: true })], total: 1 });
    renderPage();
    expect(await screen.findByText("检查结果已过期")).toBeInTheDocument();
  });

  it("never renders credential material, only the reference name", async () => {
    renderPage();
    await screen.findByText("env:LINKRAFT_KIND_TOKEN");
    expect(document.body.textContent).not.toContain("test-token-material");
  });

  it("triggers a connectivity check and reloads", async () => {
    mocks.runConnectivityCheck.mockResolvedValue({
      check_status: "ok", error_code: null, latency_ms: 9, checked_at: null, kubernetes_version: "v1.30.0",
    });
    renderPage();
    const button = await screen.findByRole("button", { name: /连通性检查/ });
    fireEvent.click(button);
    await waitFor(() => expect(mocks.runConnectivityCheck).toHaveBeenCalledWith("c1"));
    await waitFor(() => expect(mocks.listClusters).toHaveBeenCalledTimes(2));
  });

  it("surfaces a failed check by error code", async () => {
    mocks.runConnectivityCheck.mockResolvedValue({
      check_status: "failed", error_code: "KUBERNETES_TIMEOUT", latency_ms: 5000, checked_at: null,
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /连通性检查/ }));
    expect(await screen.findByText(/KUBERNETES_TIMEOUT/)).toBeInTheDocument();
  });

  it("opens the node capability drawer with live discovery data", async () => {
    mocks.listClusterNodes.mockResolvedValue({
      items: [{ hostname: "kind-control-plane", arch: "amd64", cpu_cores: "16", memory: "32Gi", gpu: "0", labels: {} }],
      total: 1,
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /节点能力/ }));
    expect(await screen.findByText("kind-control-plane")).toBeInTheDocument();
  });

  it("keeps failed clusters visible with their error code instead of hiding them", async () => {
    mocks.listClusters.mockResolvedValue({
      items: [makeCluster({ status: "connectivity_failed", last_check_error_code: "KUBERNETES_AUTH_FAILED", stale: true })],
      total: 1,
    });
    renderPage();
    expect(await screen.findByText("connectivity_failed")).toBeInTheDocument();
    expect(screen.getByText("KUBERNETES_AUTH_FAILED")).toBeInTheDocument();
  });
});
