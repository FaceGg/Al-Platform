import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AlgoOverviewPage from "./AlgoOverviewPage";

const apiGet = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({ default: { get: apiGet } }));
vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../i18n", () => ({
  useI18n: () => ({ lang: "zh", t: {}, setLang: () => {} }),
}));

describe("AlgoOverviewPage (v2 algorithm platform home)", () => {
  beforeEach(() => {
    localStorage.clear();
    apiGet.mockReset().mockImplementation((url: string) => {
      if (url === "/dashboard/stats") {
        return Promise.resolve({ data: {
          core_assets: { total_datasets: 18, total_models: 27 },
          business_stats: { total_training_jobs: 42, total_api_calls: 1904, successful_api_calls: 1889 },
          model_status: { training: 1, completed: 24, published: 2 },
          algorithm_coverage: [{ name: "LightGBM", count: 9 }, { name: "MLP", count: 5 }],
        } });
      }
      if (url === "/dashboard/top-models") {
        return Promise.resolve({ data: { items: [
          { id: "m1", name: "拧紧-hist_gradient_boosting", backbone: "hist_gradient_boosting", metrics: { f1: 0.952, recall_minority: 0.941 }, status: "completed" },
          { id: "m2", name: "电焊-extra_trees", backbone: "extra_trees", metrics: { f1: 0.938 }, status: "published" },
        ] } });
      }
      return Promise.resolve({ data: {} });
    });
  });

  it("renders KPIs from dashboard stats", async () => {
    render(<MemoryRouter><AlgoOverviewPage /></MemoryRouter>);

    expect(await screen.findByText("18")).toBeInTheDocument();
    expect(screen.getByText("27")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("1,904")).toBeInTheDocument();
    expect(screen.getByText(/成功率 99.2%/)).toBeInTheDocument();
  });

  it("renders top model versions with metric extraction", async () => {
    render(<MemoryRouter><AlgoOverviewPage /></MemoryRouter>);

    expect(await screen.findByText("拧紧-hist_gradient_boosting")).toBeInTheDocument();
    expect(screen.getByText("0.952")).toBeInTheDocument();
    expect(screen.getByText("0.941")).toBeInTheDocument();
    expect(screen.getByText("0.938")).toBeInTheDocument();
    expect(screen.getByText("-")).toBeInTheDocument(); // m2 lacks recall_minority
  });

  it("shows the failure strip when stats cannot load", async () => {
    apiGet.mockImplementation((url: string) =>
      url === "/dashboard/stats" ? Promise.reject(new Error("down")) : Promise.resolve({ data: { items: [] } }));
    render(<MemoryRouter><AlgoOverviewPage /></MemoryRouter>);

    expect(await screen.findByText(/统计数据加载失败/)).toBeInTheDocument();
  });

  it("refetches when the refresh button is pressed", async () => {
    render(<MemoryRouter><AlgoOverviewPage /></MemoryRouter>);
    await screen.findByText("18");

    fireEvent.click(screen.getByRole("button", { name: /刷新/ }));
    await waitFor(() => {
      const statsCalls = apiGet.mock.calls.filter(([url]) => url === "/dashboard/stats");
      expect(statsCalls.length).toBeGreaterThanOrEqual(2);
    });
  });
});
