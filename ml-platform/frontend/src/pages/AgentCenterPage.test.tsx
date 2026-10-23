import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentCenterPage from "./AgentCenterPage";

const apiGet = vi.hoisted(() => vi.fn());
const agentCenterMocks = vi.hoisted(() => ({
  listAgentRuns: vi.fn(),
  listPipelineRecipes: vi.fn(),
  getAgentRun: vi.fn(),
  createAgentRun: vi.fn(),
  fetchDatasetProfile: vi.fn().mockResolvedValue({
    row_count: 0,
    column_count: 0,
    columns: [],
    mutual_info_top: [],
    target: null,
  }),
  fixateRecipe: vi.fn(),
  listRecipeVersions: vi.fn().mockResolvedValue([]),
  rollbackRecipe: vi.fn(),
}));
const datasetMocks = vi.hoisted(() => ({
  listDatasets: vi.fn(),
  getDatasetPreview: vi.fn(),
}));

vi.mock("../api/client", () => ({ default: { get: apiGet } }));
vi.mock("../api/agentCenter", () => agentCenterMocks);
vi.mock("../api/datasets", () => datasetMocks);
vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));

describe("AgentCenterPage (design four-tab agent center)", () => {
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
    agentCenterMocks.getAgentRun.mockReset().mockResolvedValue({
      id: "aaaabbbb-cccc-dddd-eeee-ffff00001111", project_name: "拧紧产线", target_column: "DECIDE",
      status: "waiting_escalate", current_stage: "s4", round_count: 1, token_used: 9588, token_budget: 120000,
      llm_model_id: "deepseek-chat", error_code: "AGENT_REVIEW_ESCALATE",
      created_at: "2026-10-23T00:00:00Z", updated_at: "2026-10-23T00:01:00Z",
      guidance_json: null, result_json: {},
      memory_json: { rounds: [{
        round: 1,
        s2_attempts: [{ attempt: 1, ok: true }],
        verdict: "escalate",
        hints: ["剔除判定列后重训"],
      }] },
    });
    agentCenterMocks.listPipelineRecipes.mockReset().mockResolvedValue([
      {
        id: "11112222-3333-4444-5555-666677778888", project_name: "拧紧产线", name: "tightening-v1",
        domain: "tightening", target_column: "DECIDE", current_version: 1, version_status: "current",
        change_note: "验收通过固化", created_at: "2026-10-23T00:00:00Z", updated_at: "2026-10-23T00:00:00Z",
      },
    ]);
    datasetMocks.listDatasets.mockReset().mockResolvedValue([]);
    datasetMocks.getDatasetPreview.mockReset().mockResolvedValue({ columns: [] });
  });

  it("defaults to the wizard tab with the design step rail", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    expect(await screen.findByText(/新建向导/)).toBeInTheDocument();
    expect(screen.getByText(/数据分析/)).toBeInTheDocument();
    expect(screen.getByText(/服务化发布/)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /逐步确认模式/ })).toBeInTheDocument();
  });

  it("switches to the tasks tab with the agent-runs source and live metadata", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: /任务列表/ }));
    fireEvent.click(await screen.findByRole("button", { name: /^Agent( 运行| runs)?$/ }));
    expect(await screen.findByText(/AGENT_REVIEW_ESCALATE/)).toBeInTheDocument();
    expect(screen.getByText("拧紧产线")).toBeInTheDocument();
    expect(agentCenterMocks.listAgentRuns).toHaveBeenCalled();
  });

  it("opens the run archive timeline from an agent run row", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("tab", { name: /任务列表/ }));
    fireEvent.click(await screen.findByRole("button", { name: /^Agent( 运行| runs)?$/ }));
    const row = await screen.findByText(/aaaabbbb/);
    fireEvent.click(row.closest("tr")!);
    expect(await screen.findByText(/运行档案/)).toBeInTheDocument();
    expect(await screen.findByText(/剔除判定列后重训/)).toBeInTheDocument();
    expect(screen.getByText(/deepseek-chat/)).toBeInTheDocument();
    expect(agentCenterMocks.getAgentRun).toHaveBeenCalledWith("aaaabbbb-cccc-dddd-eeee-ffff00001111");
  });

  it("shows the AutoML jobs source with live rows", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("tab", { name: /任务列表/ }));

    expect(await screen.findByText("拧紧-自动建模")).toBeInTheDocument();
    expect(screen.getByText("电焊-验收")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/training/automl/jobs");
  });

  it("switches to the recipes tab with real rows", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: /配方库/ }));
    expect(await screen.findByText("tightening-v1")).toBeInTheDocument();
    expect(screen.getByText("验收通过固化")).toBeInTheDocument();
  });

  it("switches to the knowledge tab with the merged entry", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: /知识中心/ }));
    expect(await screen.findByText(/知识库 \+ 平台经验合并/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /进入知识中心/ })).toBeInTheDocument();
  });
});
