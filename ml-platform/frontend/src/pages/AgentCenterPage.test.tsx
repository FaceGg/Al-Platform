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
vi.mock("../api/knowledgeCenter", () => ({
  listBindings: vi.fn().mockResolvedValue([]),
  listExperience: vi.fn().mockResolvedValue([]),
  patchBinding: vi.fn(),
  retireExperience: vi.fn(),
  annotateExperience: vi.fn(),
}));
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

  it("defaults to the wizard page with the design step rail", async () => {
    render(<MemoryRouter><AgentCenterPage /></MemoryRouter>);

    expect(await screen.findByText(/新建任务/)).toBeInTheDocument();
    expect(screen.getAllByText(/数据分析/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/服务化发布/).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("switch", { name: /逐步确认模式/ }).length).toBeGreaterThan(0);
  });

  it("switches to the tasks page with the agent-runs source and live metadata", async () => {
    render(<MemoryRouter initialEntries={["/agent?tab=tasks"]}><AgentCenterPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /^Agent( 运行| runs)?$/ }));
    expect(await screen.findByText(/AGENT_REVIEW_ESCALATE/)).toBeInTheDocument();
    expect(screen.getByText("拧紧产线")).toBeInTheDocument();
    expect(agentCenterMocks.listAgentRuns).toHaveBeenCalled();
  });

  it("opens the run archive timeline from an agent run row", async () => {
    render(<MemoryRouter initialEntries={["/agent?tab=tasks"]}><AgentCenterPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /^Agent( 运行| runs)?$/ }));
    const row = await screen.findByText(/aaaabbbb/);
    fireEvent.click(row.closest("tr")!);
    expect(await screen.findByText(/运行档案/)).toBeInTheDocument();
    expect(await screen.findByText(/剔除判定列后重训/)).toBeInTheDocument();
    expect(screen.getByText(/deepseek-chat/)).toBeInTheDocument();
    expect(agentCenterMocks.getAgentRun).toHaveBeenCalledWith("aaaabbbb-cccc-dddd-eeee-ffff00001111");
  });

  it("shows the AutoML jobs source with live rows", async () => {
    render(<MemoryRouter initialEntries={["/agent?tab=tasks"]}><AgentCenterPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /AutoML/ }));
    expect(await screen.findByText("拧紧-自动建模")).toBeInTheDocument();
    expect(screen.getByText("电焊-验收")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/training/automl/jobs");
  });

  it("switches to the recipes tab with real rows", async () => {
    render(<MemoryRouter initialEntries={["/agent?tab=recipes"]}><AgentCenterPage /></MemoryRouter>);
    expect(await screen.findByText("tightening-v1")).toBeInTheDocument();
    expect(screen.getByText("验收通过固化")).toBeInTheDocument();
  });

  it("switches to the knowledge tab with the embedded center", async () => {
    render(<MemoryRouter initialEntries={["/agent?tab=knowledge"]}><AgentCenterPage /></MemoryRouter>);
    // §16.1 合并呈现：知识中心直接内嵌（绑定配置表标题来自同一 i18n 节）
    const matches = await screen.findAllByText(/绑定配置|知识中心|Knowledge/);
    expect(matches.length).toBeGreaterThan(1);
  });
});
