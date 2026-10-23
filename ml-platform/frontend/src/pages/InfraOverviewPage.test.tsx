import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import InfraOverviewPage from "./InfraOverviewPage";

const k8sMocks = vi.hoisted(() => ({ listClusters: vi.fn(), listClusterNodes: vi.fn() }));
const jobsMocks = vi.hoisted(() => ({ listJobRuns: vi.fn() }));
const notebookMocks = vi.hoisted(() => ({ listNotebooks: vi.fn() }));
const clientGet = vi.hoisted(() => vi.fn());

vi.mock("../api/kubernetes", () => k8sMocks);
vi.mock("../api/kubernetesJobs", () => jobsMocks);
vi.mock("../api/notebooks", () => notebookMocks);
vi.mock("../api/client", () => ({ default: { get: clientGet } }));
vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../i18n", () => ({
  useI18n: () => ({ lang: "zh", t: {}, setLang: () => {} }),
}));

describe("InfraOverviewPage (v2 infrastructure home)", () => {
  beforeEach(() => {
    localStorage.clear();
    k8sMocks.listClusters.mockReset().mockResolvedValue({
      items: [
        { id: "c1", display_name: "w13", name: "w13", status: "connected", kubernetes_version: "v1.31", last_check_latency_ms: 42, last_checked_at: "2026-10-23T00:00:00Z" },
        { id: "c2", display_name: "w16b", name: "w16b", status: "unreachable", last_check_error_code: "TLS_HANDSHAKE", kubernetes_version: null, last_check_latency_ms: null, last_checked_at: null },
      ],
      total: 2,
    });
    k8sMocks.listClusterNodes.mockReset().mockImplementation((clusterId: string) =>
      Promise.resolve({ items: clusterId === "c1"
        ? [{ hostname: "w13-control", cpu_cores: "8", memory: "16Gi", gpu: "0", arch: "amd64" }]
        : [], total: clusterId === "c1" ? 1 : 0 }));
    jobsMocks.listJobRuns.mockReset().mockResolvedValue({
      items: [
        { id: "j1", job_name: "automl-tighten-r2", namespace: "ml-agent", image_ref: "automl-cpu:3.11", status: "running", submitted_at: "2026-10-23T00:00:00Z" },
        { id: "j2", job_name: "feat-preview-81", namespace: "ml-agent", image_ref: "sandbox:3.11", status: "succeeded", submitted_at: "2026-10-22T00:00:00Z" },
      ],
      total: 2,
    });
    notebookMocks.listNotebooks.mockReset().mockResolvedValue({ items: [], total: 3 });
    clientGet.mockReset().mockResolvedValue({ data: {} });
  });

  it("renders cluster KPIs and the cluster table with health badges", async () => {
    render(<MemoryRouter><InfraOverviewPage /></MemoryRouter>);

    expect(await screen.findByText("w13", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByText("w16b", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByText("1/2 连通")).toBeInTheDocument();
    expect(screen.getByText("TLS_HANDSHAKE")).toBeInTheDocument();
    expect(screen.getByText("v1.31")).toBeInTheDocument();
    expect(screen.getByText("42ms")).toBeInTheDocument();
  });

  it("lists recent jobs and the notebook session total", async () => {
    render(<MemoryRouter><InfraOverviewPage /></MemoryRouter>);

    expect(await screen.findByText("automl-tighten-r2")).toBeInTheDocument();
    expect(screen.getByText("feat-preview-81")).toBeInTheDocument();
    expect(screen.getByText("1 运行/排队中")).toBeInTheDocument();
    expect(notebookMocks.listNotebooks).toHaveBeenCalled();
  });

  it("shows empty states when nothing is connected", async () => {
    k8sMocks.listClusters.mockResolvedValue({ items: [], total: 0 });
    jobsMocks.listJobRuns.mockResolvedValue({ items: [], total: 0 });
    render(<MemoryRouter><InfraOverviewPage /></MemoryRouter>);

    expect(await screen.findByText(/暂无接入集群/)).toBeInTheDocument();
    expect(screen.getByText(/暂无作业记录/)).toBeInTheDocument();
  });
});
