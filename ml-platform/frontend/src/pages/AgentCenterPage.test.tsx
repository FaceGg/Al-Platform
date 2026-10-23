import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentCenterPage from "./AgentCenterPage";

const apiGet = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({ default: { get: apiGet } }));
vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));

describe("AgentCenterPage (v2 agent center)", () => {
  beforeEach(() => {
    localStorage.clear();
    apiGet.mockReset();
    apiGet.mockResolvedValue({ data: { items: [
      { id: 11, name: "拧紧-自动建模", status: "running", progress: 42, updated_at: "2026-10-23T00:00:00Z" },
      { id: 12, name: "电焊-验收", status: "completed", progress: 100, updated_at: "2026-10-22T00:00:00Z" },
    ] } });
  });

  it("renders the KPI row and the jobs table with live data", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    expect(await screen.findByText("拧紧-自动建模")).toBeInTheDocument();
    expect(screen.getByText("电焊-验收")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/training/automl/jobs");
  });

  it("switches to the wizard tab with the four steps and launch affordance", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: /建模向导|Wizard/ }));
    expect(await screen.findByText("四步向导 · 全自动建模迭代")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /启动向导|Launch wizard/ })).toBeInTheDocument();
  });

  it("switches to the recipes tab and surfaces the pending-API note", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: /配方库|Recipes/ }));
    expect(await screen.findByText(/配方服务化接口接入中|Recipe serving APIs/)).toBeInTheDocument();
  });

  it("shows the empty hint when the jobs list is empty", async () => {
    apiGet.mockResolvedValue({ data: { items: [] } });
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    await waitFor(() => expect(screen.getByText(/暂无任务/)).toBeInTheDocument());
  });
});
