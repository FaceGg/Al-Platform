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
});
