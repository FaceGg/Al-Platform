import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import DashboardPage from "./DashboardPage";

const apiGet = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({ apiGet }));
vi.mock("../components/AppLayout", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("../i18n", () => ({ useI18n: () => ({ lang: "zh" }) }));
vi.mock("../stores/themeContext", () => ({ useTheme: () => ({ theme: "light" }) }));
vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="chart" />,
}));

describe("DashboardPage", () => {
  beforeEach(() => {
    apiGet.mockImplementation((path: string) => Promise.resolve(
      path === "/dashboard/stats"
        ? { core_assets: { total_algorithms: 7 }, model_status: {}, algorithm_coverage: [] }
        : { items: [] },
    ));
  });

  it("labels built-in dashboard assets as operators", async () => {
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect((await screen.findAllByText("内置算子")).length).toBeGreaterThan(0);
    expect(screen.queryByText("内置算法")).not.toBeInTheDocument();
  });

  it("renders real dashboard values and recent projects from the API", async () => {
    apiGet.mockImplementation((path: string) => Promise.resolve(
      path === "/dashboard/stats"
        ? {
            core_assets: { total_algorithms: 12, total_datasets: 8, total_models: 5, total_apis: 3 },
            model_status: { training: 1, completed: 3, published: 1 },
            algorithm_coverage: [{ category: "ml", count: 12 }],
          }
        : { items: [{ id: "project-1", name: "焊点质量项目", description: "生产线数据" }] },
    ));

    render(<MemoryRouter><DashboardPage /></MemoryRouter>);

    expect(await screen.findByText("12")).toBeInTheDocument();
    expect(screen.getByText("焊点质量项目")).toBeInTheDocument();
    expect(screen.getByText("生产线数据")).toBeInTheDocument();
  });

  it("shows an explicit error state when dashboard data cannot be loaded", async () => {
    apiGet.mockRejectedValue(new Error("dashboard unavailable"));

    render(<MemoryRouter><DashboardPage /></MemoryRouter>);

    expect(await screen.findByText("工作台数据加载失败")).toBeInTheDocument();
  });
});
