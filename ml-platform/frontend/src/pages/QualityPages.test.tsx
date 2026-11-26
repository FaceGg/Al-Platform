import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LangProvider } from "../i18n";
import { ThemeProvider } from "../stores/themeContext";
import { App as AntApp } from "antd";

const mocks = vi.hoisted(() => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  formatApiError: vi.fn((_e: unknown, fallback: string) => fallback),
}));

vi.mock("../api/client", () => ({
  default: mocks.apiClient,
  formatApiError: mocks.formatApiError,
}));

import ProductionRecordsPage from "./ProductionRecordsPage";
import QualityScenesPage from "./QualityScenesPage";
import QualityStationsPage from "./QualityStationsPage";
import HelpCenterPage from "./HelpCenterPage";

function renderPage(node: React.ReactElement, initialEntries = ["/"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <LangProvider><ThemeProvider><AntApp>{node}</AntApp></ThemeProvider></LangProvider>
    </MemoryRouter>,
  );
}

describe("ProductionRecordsPage（生产记录）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation((url: string) => {
      if (url === "/projects") {
        return Promise.resolve({ data: { items: [{ id: "p1", name: "项目一" }] } });
      }
      if (url === "/projects/p1/quality-scenes") {
        return Promise.resolve({ data: { items: [{ id: "s1", code: "S1", name: "场景一", field_roles: {} }] } });
      }
      if (url === "/projects/p1/quality-stations") {
        return Promise.resolve({ data: { items: [{ id: "st1", code: "ST1", name: "工位一", scene_id: "s1", enabled: true }] } });
      }
      if (url === "/projects/p1/inference-results") {
        return Promise.resolve({ data: { items: [
          { id: "r1", request_id: "q1", sample_key: "VIN-A", channel: "online", is_anomaly: true, anomaly_score: 0.9, batch_no: "B1", occurred_at: "2026-11-25T09:00:00" },
          { id: "r2", request_id: "q2", sample_key: null, channel: "demo", is_anomaly: false, occurred_at: "2026-11-25T09:01:00" },
        ], total: 2, page: 1, page_size: 20 } });
      }
      if (url === "/projects/p1/inference-results/summary") {
        return Promise.resolve({ data: { total: 12, ok_count: 9, anomaly_count: 3, buckets: [] } });
      }
      return Promise.resolve({ data: {} });
    });
  });

  it("renders result rows with anomaly tags and summary cards", async () => {
    renderPage(<ProductionRecordsPage />);
    expect(await screen.findByText("VIN-A")).toBeInTheDocument();
    expect(screen.getAllByText("异常").length).toBeGreaterThan(0);
    // 演示隔离：demo 通道行由后端默认排除，页面不展示通道切换外的 demo 行
    await waitFor(() => expect(screen.getAllByText("12").length).toBeGreaterThan(0));
  });

  it("queries with sample key filter and pagination params", async () => {
    renderPage(<ProductionRecordsPage />);
    await screen.findByText("VIN-A");
    const input = screen.getByLabelText("样本键");
    fireEvent.change(input, { target: { value: "VIN-A" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => {
      const calls = mocks.apiClient.get.mock.calls.filter(([url]) => url === "/projects/p1/inference-results");
      const call = calls[calls.length - 1];
      expect(call?.[1]?.params?.sample_key).toBe("VIN-A");
    });
  });
});

describe("QualityScenesPage（场景管理）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation((url: string) => {
      if (url === "/projects") {
        return Promise.resolve({ data: { items: [{ id: "p1", name: "项目一" }] } });
      }
      if (url === "/projects/p1/quality-scenes") {
        return Promise.resolve({ data: { items: [
          { id: "s1", code: "S1", name: "点焊场景", field_roles: { sample_key: "vin", target: "ng" }, condition_column: "station_id", updated_at: "2026-11-25T09:00:00" },
        ] } });
      }
      if (url === "/projects/p1/quality-scenes/s1/spec-limits") {
        return Promise.resolve({ data: { items: [
          { id: "sp1", field: "torque", statistic: "value", usl: 1.5, lsl: 0.5, target: 1.0, unit: "N*m" },
        ] } });
      }
      return Promise.resolve({ data: {} });
    });
  });

  it("lists scenes with field role tags", async () => {
    renderPage(<QualityScenesPage />);
    expect(await screen.findByText("点焊场景")).toBeInTheDocument();
    expect(screen.getByText(/样本键: vin/)).toBeInTheDocument();
    expect(screen.getByText(/目标列: ng/)).toBeInTheDocument();
  });

  it("opens the create form and posts scene payload", async () => {
    mocks.apiClient.post.mockResolvedValue({ data: { id: "s2" } });
    mocks.apiClient.put.mockResolvedValue({ data: {} });
    renderPage(<QualityScenesPage />);
    fireEvent.click(await screen.findByRole("button", { name: /新建场景/ }));
    fireEvent.change(await screen.findByLabelText("编码"), { target: { value: "S2" } });
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "拧紧场景" } });
    fireEvent.click(screen.getByRole("button", { name: /保 存/ }));
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith(
      "/projects/p1/quality-scenes",
      expect.objectContaining({ code: "S2", name: "拧紧场景" }),
    ));
  });

  it("opens spec drawer and loads spec limits", async () => {
    renderPage(<QualityScenesPage />);
    expect(await screen.findByText("点焊场景")).toBeInTheDocument();
    // antd 两字中文按钮自动插空格：「规格」渲染为「规 格」
    const specButtons = await screen.findAllByRole("button", { name: /规\s*格/ });
    fireEvent.click(specButtons[0]);
    expect(await screen.findByText(/torque/)).toBeInTheDocument();
  });
});

describe("HelpCenterPage（帮助中心）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
    mocks.apiClient.get.mockResolvedValue({ data: {} });
  });

  it("lists chapters and opens the located chapter for this page", async () => {
    renderPage(<HelpCenterPage />, ["/help?page=/quality/production-records"]);
    expect(await screen.findByText("本页帮助：生产记录")).toBeInTheDocument();
    expect(screen.getByText("生产记录")).toBeInTheDocument();
  });

  it("searches chapters by body substring", async () => {
    renderPage(<HelpCenterPage />);
    const input = await screen.findByLabelText("搜索帮助");
    fireEvent.change(input, { target: { value: "规格定义" } });
    // 规格定义出现在场景管理章正文
    expect(screen.getByText(/…/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("场景管理"));
  });

  it("falls back to the chapter directory without page mapping", () => {
    renderPage(<HelpCenterPage />, ["/help"]);
    expect(screen.getByText("章节目录")).toBeInTheDocument();
    expect(screen.getAllByText("平台说明").length).toBeGreaterThan(0);
  });
});

describe("QualityStationsPage（工位与设备）", () => {
  const recentHeartbeat = new Date(Date.now() - 10_000).toISOString();
  const staleHeartbeat = new Date(Date.now() - 10 * 60_000).toISOString();

  const setupStations = (devices: unknown[]) => {
    mocks.apiClient.get.mockImplementation((url: string) => {
      if (url === "/projects") {
        return Promise.resolve({ data: { items: [{ id: "p1", name: "项目一" }] } });
      }
      if (url === "/auth/me") {
        return Promise.resolve({ data: { id: "u1", username: "qc", role: "engineer" } });
      }
      if (url === "/projects/p1/quality-scenes") {
        return Promise.resolve({ data: { items: [{ id: "s1", code: "S1", name: "场景一", field_roles: {} }] } });
      }
      if (url === "/projects/p1/quality-stations") {
        return Promise.resolve({ data: { items: [
          { id: "st1", code: "ST1", name: "工位一", scene_id: "s1", enabled: true, edge_device_id: "d1" },
          { id: "st2", code: "ST2", name: "工位二", scene_id: "s1", enabled: true, edge_device_id: "d2" },
          { id: "st3", code: "ST3", name: "工位三", scene_id: "s1", enabled: true, edge_device_id: null },
        ] } });
      }
      if (url === "/compute/devices") {
        return Promise.resolve({ data: devices });
      }
      return Promise.resolve({ data: {} });
    });
  };

  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
  });

  it("marks bound devices online/offline by heartbeat freshness (B1-10 验收④)", async () => {
    setupStations([
      { id: "d1", name: "网关机-01", last_heartbeat: recentHeartbeat },
      { id: "d2", name: "网关机-02", last_heartbeat: staleHeartbeat },
    ]);
    renderPage(<QualityStationsPage />);

    expect(await screen.findByText("工位一")).toBeInTheDocument();
    // 设备清单异步到达后重渲染：新鲜心跳在线、过期心跳离线
    expect(await screen.findByText("在线")).toBeInTheDocument();
    expect(screen.getByText("离线")).toBeInTheDocument();
    // 绑定的设备名列出设备名，未绑定工位显示占位短横
    expect(await screen.findByText("网关机-01")).toBeInTheDocument();
    expect(screen.getByText("网关机-02")).toBeInTheDocument();
  });

  it("renders the shadow state placeholder for all rows (B4-02 预留)", async () => {
    setupStations([{ id: "d1", name: "网关机-01", last_heartbeat: recentHeartbeat }]);
    renderPage(<QualityStationsPage />);

    expect(await screen.findByText("工位一")).toBeInTheDocument();
    // 影子列的「未启用」占位随每行渲染（B4-02 正式落地前）
    expect(await screen.findAllByText("未启用")).not.toEqual([]);
  });
});
