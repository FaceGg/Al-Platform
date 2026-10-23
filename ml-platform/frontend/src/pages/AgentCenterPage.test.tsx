import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentCenterPage from "./AgentCenterPage";

const apiGet = vi.hoisted(() => vi.fn());
const agentCenterMocks = vi.hoisted(() => ({
  listAgentRuns: vi.fn(),
  listPipelineRecipes: vi.fn(),
}));

vi.mock("../api/client", () => ({ default: { get: apiGet } }));
vi.mock("../api/agentCenter", () => ({
  listAgentRuns: agentCenterMocks.listAgentRuns,
  listPipelineRecipes: agentCenterMocks.listPipelineRecipes,
}));
vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));

describe("AgentCenterPage (v2 agent center)", () => {
  beforeEach(() => {
    localStorage.clear();
    apiGet.mockReset();
    apiGet.mockResolvedValue({ data: { items: [
      { id: 11, name: "拧紧-自动建模", status: "running", progress: 42, updated_at: "2026-10-23T00:00:00Z" },
      { id: 12, name: "电焊-验收", status: "completed", progress: 100, updated_at: "2026-10-22T00:00:00Z" },
    ] } });
    agentCenterMocks.listAgentRuns.mockReset().mockResolvedValue([
      {
        id: "aaaabbbb-cccc-dddd-eeee-ffff00001111", project_name: "拧紧产线", target_column: "DECIDE",
        status: "waiting_escalate", current_stage: "s4", round_count: 1, token_used: 9588,
        error_code: "AGENT_REVIEW_ESCALATE", created_at: "2026-10-23T00:00:00Z", updated_at: "2026-10-23T00:01:00Z",
      },
    ]);
    agentCenterMocks.listPipelineRecipes.mockReset().mockResolvedValue([
      {
        id: "11112222-3333-4444-5555-666677778888", project_name: "拧紧产线", name: "tightening-v1",
        domain: "tightening", target_column: "DECIDE", current_version: 1, version_status: "current",
        change_note: "验收通过固化", created_at: "2026-10-23T00:00:00Z", updated_at: "2026-10-23T00:00:00Z",
      },
    ]);
  });

  it("renders the KPI row and the jobs table with live data", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    expect(await screen.findByText("拧紧-自动建模")).toBeInTheDocument();
    expect(screen.getByText("电焊-验收")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/training/automl/jobs");
  });

  it("switches to the wizard tab and renders the interactive four-step wizard", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: /建模向导|Wizard/ }));
    expect(await screen.findByText(/选择项目与数据/)).toBeInTheDocument();
    expect(screen.getByLabelText("选择项目")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /下一步/ })).toBeDisabled();
  });

  it("switches to the recipes tab and surfaces the pending-API note", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: /配方库|Recipes/ }));
    expect(await screen.findByText("tightening-v1")).toBeInTheDocument();
    expect(screen.getByText("验收通过固化")).toBeInTheDocument();
    expect(agentCenterMocks.listPipelineRecipes).toHaveBeenCalled();
  });

  it("switches the jobs table to the agent-runs source with live metadata", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /^Agent( 运行| runs)?$/ }));
    expect(await screen.findByText(/AGENT_REVIEW_ESCALATE/)).toBeInTheDocument();
    expect(screen.getByText("拧紧产线")).toBeInTheDocument();
    expect(screen.getByText(/9,588/)).toBeInTheDocument();
    expect(agentCenterMocks.listAgentRuns).toHaveBeenCalled();
  });

  it("shows the agent-runs empty state when the platform has no runs", async () => {
    agentCenterMocks.listAgentRuns.mockResolvedValue([]);
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /^Agent( 运行| runs)?$/ }));
    expect(await screen.findByText(/暂无 Agent 运行记录|No agent runs yet/)).toBeInTheDocument();
  });

  it("shows the empty hint when the jobs list is empty", async () => {
    apiGet.mockResolvedValue({ data: { items: [] } });
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    await waitFor(() => expect(screen.getByText(/暂无任务/)).toBeInTheDocument());
  });
});
