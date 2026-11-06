import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AlgoOverviewPage from "./AlgoOverviewPage";
import { DASHBOARD_STATS_CHANGED } from "../events/dashboardStats";

const apiGet = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({ default: { get: apiGet } }));
vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../i18n", () => ({
  useI18n: () => ({ lang: "zh", t: {}, setLang: () => {} }),
}));

const callsTo = (url: string) => apiGet.mock.calls.filter(([called]) => called === url).length;

function renderPage() {
  return render(<MemoryRouter><AlgoOverviewPage /></MemoryRouter>);
}

describe("AlgoOverviewPage (v2 algorithm platform home)", () => {
  beforeEach(() => {
    localStorage.clear();
    apiGet.mockReset().mockImplementation((url: string) => {
      if (url === "/dashboard/stats") {
        return Promise.resolve({ data: {
          core_assets: { total_datasets: 18, total_models: 27 },
          business_stats: { total_training_jobs: 42, total_api_calls: 1904, successful_api_calls: 1889 },
          model_status: { training: 1, completed: 24, published: 2 },
          model_algorithm_coverage: [
            { name: "lightgbm", count: 3 },
            { name: "ensemble", count: 1 },
            { name: "unknown", count: 1 },
          ],
        } });
      }
      if (url === "/dashboard/recent-model-versions") {
        return Promise.resolve({ data: { items: [
          {
            id: "v-new", model_name: "拧紧质量模型", version_number: 2, algorithm: "hist_gradient_boosting",
            metrics: { f1: 0.952, recall_minority: 0.941 }, approval_status: "approved", lifecycle_state: "enabled",
            published: true, created_at: "2026-11-06T07:30:00",
          },
          {
            id: "v-old", model_name: "点焊集成模型", version_number: 1, algorithm: "ensemble",
            // 集成版本的指标嵌在 metrics.metrics 里
            metrics: { name: "集成加权投票", metrics: { f1: 0.938 } }, approval_status: "pending", lifecycle_state: "pending_review",
            published: false, created_at: "2026-11-06T07:00:00",
          },
        ] } });
      }
      return Promise.resolve({ data: {} });
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders KPIs from dashboard stats", async () => {
    renderPage();

    expect(await screen.findByText("18")).toBeInTheDocument();
    expect(screen.getByText("27")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("1,904")).toBeInTheDocument();
    expect(screen.getByText(/成功率 99.2%/)).toBeInTheDocument();
  });

  it("drops the legacy description sentence from the page header", async () => {
    renderPage();
    await screen.findByText("18");
    expect(screen.queryByText(/原全局仪表板收拢为算法平台首页/)).not.toBeInTheDocument();
  });

  it("lists the most recently registered model versions from the model registry", async () => {
    renderPage();

    const newest = await screen.findByText("拧紧质量模型");
    expect(apiGet).toHaveBeenCalledWith("/dashboard/recent-model-versions", { params: { limit: 6 } });
    expect(apiGet).not.toHaveBeenCalledWith("/dashboard/top-models");
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("cell")[0].firstChild?.textContent)).toEqual(["拧紧质量模型", "点焊集成模型"]);
    const [first, second] = rows;
    expect(within(first).getByText(/^v2 · /)).toBeInTheDocument();
    expect(within(first).getByText("HistGradientBoosting")).toBeInTheDocument();
    expect(within(first).getByText("0.952")).toBeInTheDocument();
    expect(within(first).getByText("0.941")).toBeInTheDocument();
    expect(within(first).getByText("已发布")).toBeInTheDocument();
    expect(within(second).getByText("集成加权投票")).toBeInTheDocument();
    expect(within(second).getByText("0.938")).toBeInTheDocument();
    expect(within(second).getByText("-")).toBeInTheDocument();
    expect(within(second).getByText("待审批")).toBeInTheDocument();
    expect(newest).toBeInTheDocument();
  });

  it("shows which algorithm each coverage count belongs to", async () => {
    renderPage();

    const panel = (await screen.findByText("LightGBM")).closest(".v2-panel") as HTMLElement;
    expect(within(panel).getByText("算法覆盖")).toBeInTheDocument();
    const rows = Array.from(panel.querySelectorAll("div[style*='padding: 4px 0']")).map((row) => row.textContent);
    expect(rows).toEqual(["LightGBM3", "集成加权投票1", "未标注算法1"]);
  });

  it("shows the empty state once every model version is gone", async () => {
    apiGet.mockImplementation((url: string) => {
      if (url === "/dashboard/stats") return Promise.resolve({ data: { core_assets: { total_models: 0 }, model_algorithm_coverage: [] } });
      if (url === "/dashboard/recent-model-versions") return Promise.resolve({ data: { items: [] } });
      return Promise.resolve({ data: {} });
    });
    renderPage();

    expect(await screen.findByText(/暂无模型版本/)).toBeInTheDocument();
    expect(screen.getByText("暂无数据")).toBeInTheDocument();
  });

  it("shows the failure strip when stats cannot load", async () => {
    apiGet.mockImplementation((url: string) =>
      url === "/dashboard/stats" ? Promise.reject(new Error("down")) : Promise.resolve({ data: { items: [] } }));
    renderPage();

    expect(await screen.findByText(/统计数据加载失败/)).toBeInTheDocument();
  });

  it("refetches when the refresh button is pressed", async () => {
    renderPage();
    await screen.findByText("18");

    fireEvent.click(screen.getByRole("button", { name: /刷新/ }));
    await waitFor(() => {
      expect(callsTo("/dashboard/stats")).toBeGreaterThanOrEqual(2);
      expect(callsTo("/dashboard/recent-model-versions")).toBeGreaterThanOrEqual(2);
    });
  });

  it("refreshes on its own every 15 seconds and shows when it last updated", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderPage();
    await screen.findByText("18");
    expect(screen.getByText(/每 15 秒自动刷新 · 更新于/)).toBeInTheDocument();
    const before = callsTo("/dashboard/recent-model-versions");

    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(callsTo("/dashboard/recent-model-versions")).toBe(before + 1);
    expect(callsTo("/dashboard/stats")).toBe(before + 1);

    // 页面在后台时跳过自动刷新
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(callsTo("/dashboard/recent-model-versions")).toBe(before + 1);
  });

  it("refreshes immediately when another page changes data or the page becomes visible again", async () => {
    renderPage();
    await screen.findByText("18");
    const before = callsTo("/dashboard/recent-model-versions");

    act(() => { window.dispatchEvent(new CustomEvent(DASHBOARD_STATS_CHANGED)); });
    await waitFor(() => expect(callsTo("/dashboard/recent-model-versions")).toBe(before + 1));

    act(() => { window.dispatchEvent(new StorageEvent("storage", { key: DASHBOARD_STATS_CHANGED })); });
    await waitFor(() => expect(callsTo("/dashboard/recent-model-versions")).toBe(before + 2));

    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    await waitFor(() => expect(callsTo("/dashboard/recent-model-versions")).toBe(before + 3));
  });
});
