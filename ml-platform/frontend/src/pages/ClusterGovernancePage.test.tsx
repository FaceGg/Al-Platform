import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ClusterGovernancePage from "./ClusterGovernancePage";

const mocks = vi.hoisted(() => ({
  listRoutingPolicies: vi.fn(),
  listStorageBindings: vi.fn(),
  listQuotaPolicies: vi.fn(),
  listReservations: vi.fn(),
  listUsage: vi.fn(),
  routingPreview: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/clusterGovernance", () => mocks);
vi.mock("../api/client", () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { items: [{ id: "p1", name: "w16 项目" }] } }),
  },
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      clusterGovernance: {
        title: "集群治理", refresh: "刷新", preview: "路由预演", previewTitle: "路由预演",
        selected: "选中", reason: "原因", cluster: "集群", eligible: "是否可选",
        policiesTitle: "路由策略", bindingsTitle: "存储绑定", quotasTitle: "资源配额",
        reservationsTitle: "活跃预留", usageTitle: "用量快照",
        priority: "优先级", policy: "策略", revision: "版本", mode: "类型", target: "目标",
        access: "访问", scope: "范围", quota: "配额", operation: "操作", state: "状态",
        reserved: "预留量", releaseReason: "释放原因", subject: "对象", metrics: "指标",
        truncated: "截断", staleWarning: "部分集群用量快照已过期(采集失败或断源)",
        loadFailed: "加载失败", previewFailed: "预演失败",
      },
    },
  }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listRoutingPolicies.mockResolvedValue({
    items: [{ id: "rp1", project_id: "p1", priority: 1, policy_json: { region: "cn-east" }, revision: 3 }],
  });
  mocks.listStorageBindings.mockResolvedValue({
    items: [
      {
        id: "sb1", cluster_id: "c1", mode: "object_prefix",
        pvc_name: null, object_prefix: "projects/p1/data/", access: "read_only", status: "active",
      },
    ],
  });
  mocks.listQuotaPolicies.mockResolvedValue({
    items: [{ id: "q1", scope: "project", scope_id: "p1", quota_json: { cpu_cores: 8, max_concurrent_jobs: 6 }, revision: 2 }],
  });
  mocks.listReservations.mockResolvedValue({
    items: [
      {
        id: "r1", project_id: "p1", cluster_id: "c1", operation_id: "op-1",
        reserved_json: { cpu_cores: 1 }, state: "active", release_reason: null,
      },
      {
        id: "r2", project_id: "p1", cluster_id: "c1", operation_id: "op-2",
        reserved_json: { cpu_cores: 1 }, state: "released", release_reason: "terminal",
      },
    ],
  });
  mocks.listUsage.mockResolvedValue({
    items: [
      {
        id: "u1", cluster_id: "c1", scope: "node", subject: "kind-control-plane",
        metrics_json: { cpu_cores: 0.25 }, truncated: false, collected_at: new Date().toISOString(),
      },
      {
        id: "u2", cluster_id: "c1", scope: "pod", subject: "pod-1",
        metrics_json: { cpu_cores: 0.08 }, truncated: true, collected_at: new Date().toISOString(),
      },
    ],
    stale_by_cluster: { c1: true },
  });
  mocks.routingPreview.mockResolvedValue({
    selected_cluster_id: "c1",
    reason: "region_match",
    policy_revision: 3,
    candidates: [
      { cluster_id: "c1", name: "healthy", excluded: false, reason: null },
      { cluster_id: "c2", name: "broken", excluded: true, reason: "cluster_not_active" },
    ],
  });
});

function renderPage() {
  return render(
    <AntApp>
      <ClusterGovernancePage />
    </AntApp>,
  );
}

describe("ClusterGovernancePage", () => {
  it("renders policies, bindings, quotas and reservations", async () => {
    renderPage();
    expect(await screen.findByText(/"cn-east"/)).toBeInTheDocument();
    expect(screen.getByText("projects/p1/data/")).toBeInTheDocument();
    expect(screen.getByText("read_only")).toBeInTheDocument();
    expect(screen.getByText("cpu_cores=8")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByText("terminal")).toBeInTheDocument();
  });

  it("shows stale and truncated markers on usage snapshots", async () => {
    renderPage();
    expect(await screen.findByText(/部分集群用量快照已过期/)).toBeInTheDocument();
    expect(await screen.findByText("truncated")).toBeInTheDocument();
  });

  it("renders the routing preview with per-cluster exclusion reasons", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /路由预演/ }));
    // Slow CI machines need a generous timeout for the async preview render.
    await waitFor(
      () => expect(screen.getByText(/region_match/)).toBeInTheDocument(),
      { timeout: 10_000 },
    );
    await waitFor(
      () => expect(screen.getByText("cluster_not_active")).toBeInTheDocument(),
      { timeout: 10_000 },
    );
    expect(screen.getByText("healthy")).toBeInTheDocument();
    expect(screen.getByText("broken")).toBeInTheDocument();
    await waitFor(() => expect(mocks.routingPreview).toHaveBeenCalledWith("p1"));
  });

  it("shows quota labels with their limits", async () => {
    renderPage();
    expect(await screen.findByText("max_concurrent_jobs=6")).toBeInTheDocument();
  });
});
