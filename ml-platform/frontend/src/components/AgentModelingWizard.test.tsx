import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentModelingWizard from "./AgentModelingWizard";

const clientGet = vi.hoisted(() => vi.fn());
const clientPost = vi.hoisted(() => vi.fn());
const datasetMocks = vi.hoisted(() => ({
  listDatasets: vi.fn(),
  getDatasetPreview: vi.fn(),
}));
const agentCenterMocks = vi.hoisted(() => ({
  createAgentRun: vi.fn(),
  listAgentRuns: vi.fn().mockResolvedValue([]),
  getAgentRun: vi.fn().mockResolvedValue({ memory_json: { rounds: [] }, result_json: {} }),
  fetchDatasetProfile: vi.fn().mockResolvedValue({
    row_count: 10,
    column_count: 2,
    columns: [
      { name: "F1", base_name: "F1", semantic: null, missing_rate: 0, cardinality: 10, constant: false },
      { name: "target", base_name: "target", semantic: null, missing_rate: 0, cardinality: 2, constant: false },
    ],
    mutual_info_top: [{ column: "F1", mi: 0.5 }],
    target: { distribution: { "1": 5, "0": 5 }, imbalance_ratio: 1 },
  }),
  fixateRecipe: vi.fn(),
  listRecipeVersions: vi.fn().mockResolvedValue([]),
  rollbackRecipe: vi.fn(),
}));

vi.mock("../api/client", () => ({ default: { get: clientGet, post: clientPost } }));
vi.mock("../api/datasets", () => datasetMocks);
vi.mock("../api/agentCenter", () => agentCenterMocks);
vi.mock("../pages/AutoMLPage", () => ({
  AUTOML_ALGORITHM_OPTIONS: [
    { value: "lightgbm", label: "LightGBM" },
    { value: "mlp", label: "MLP" },
  ],
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({ lang: "zh", t: {}, setLang: () => {} }),
}));

function renderWizard() {
  return render(<MemoryRouter><AgentModelingWizard /></MemoryRouter>);
}

describe("AgentModelingWizard (design five-step agent wizard)", () => {
  beforeEach(() => {
    localStorage.clear();
    clientGet.mockReset().mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "p1", name: "拧紧" }] } });
      if (url === "/llm-profiles") {
        return Promise.resolve({ data: [{ id: "prof-1", name: "内置默认档案", model_id: "deepseek-chat", is_default: true }] });
      }
      return Promise.resolve({ data: {} });
    });
    datasetMocks.listDatasets.mockReset().mockResolvedValue([
      { id: "d1", name: "tighten_train.csv", row_count: 70087, column_count: 20 },
    ]);
    datasetMocks.getDatasetPreview.mockReset().mockResolvedValue({
      columns: ["ACTUAL_TORQUE", "TARGET_TORQUE", "DECIDE(判定（最终判定）（0-不合格，1-合格）)"],
    });
    agentCenterMocks.createAgentRun.mockReset().mockResolvedValue({ id: "run-1", status: "pending" });
  });

  it("walks the five steps and archives guidance through POST /agent/runs", async () => {
    renderWizard();

    // Config bar: project, dataset, auto-selected DECIDE target, default profile.
    fireEvent.change(await screen.findByLabelText("选择项目"), { target: { value: "p1" } });
    fireEvent.change(await screen.findByLabelText("选择数据集"), { target: { value: "d1" } });
    await waitFor(() => expect(screen.getByLabelText("选择目标列").querySelectorAll("option").length).toBeGreaterThan(1));
    expect(screen.getByLabelText("选择目标列")).toHaveValue("DECIDE(判定（最终判定）（0-不合格，1-合格）)");

    // Step 1: check a column and add a note; add an analysis prompt.
    const torqueCheck = screen.getByLabelText("select ACTUAL_TORQUE");
    fireEvent.click(torqueCheck);
    const noteBox = screen.getAllByPlaceholderText("选中的列与备注会成为大模型的重点输入")[0];
    fireEvent.change(noteBox, { target: { value: "核心质量信号，关注偏差" } });
    fireEvent.change(screen.getByPlaceholderText(/这批数据来自换夹具/), { target: { value: "关注工装漂移" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));

    // Step 2: default mixed shape; mark DECIDE-like column as keep via directive.
    fireEvent.click(await screen.findByText(/表格数据/));
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));

    // Step 3: whitelist one algorithm.
    fireEvent.click(await screen.findByText("LightGBM"));
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));

    // Step 4: gates default blank (不设门禁)；keep and launch.
    expect(await screen.findByText(/验收指标阈值/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));

    // Step 5: launch.
    fireEvent.click(await screen.findByRole("button", { name: /^rocket 启动智能体$/ }));

    await waitFor(() => expect(agentCenterMocks.createAgentRun).toHaveBeenCalledTimes(1));
    const payload = agentCenterMocks.createAgentRun.mock.calls[0][0];
    expect(payload.dataset_artifact_id).toBe("d1");
    expect(payload.target_column).toContain("判定");
    expect(payload.project_id).toBe("p1");
    expect(payload.llm_profile_id).toBe("prof-1");
    expect(payload.step_by_step).toBe(false);
    expect(payload.guidance.analysis.column_notes).toEqual([
      { column: "ACTUAL_TORQUE", note: "核心质量信号，关注偏差" },
    ]);
    expect(payload.guidance.analysis.prompts).toEqual(["关注工装漂移"]);
    expect(payload.guidance.feature.data_shape).toBe("tabular");
    expect(payload.guidance.modeling.algorithm_whitelist).toEqual(["lightgbm"]);
    expect(payload.guidance.evaluation.metric_gates).toEqual({});
  });

  it("expands step-by-step mode into the pause plan on submit", async () => {
    renderWizard();
    fireEvent.change(await screen.findByLabelText("选择项目"), { target: { value: "p1" } });
    fireEvent.change(await screen.findByLabelText("选择数据集"), { target: { value: "d1" } });
    await waitFor(() => expect(screen.getByLabelText("选择目标列").querySelectorAll("option").length).toBeGreaterThan(1));
    const toggle = screen.getByRole("switch", { name: "逐步确认模式" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
    for (let i = 0; i < 4; i += 1) {
      fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    }
    fireEvent.click(await screen.findByRole("button", { name: /^rocket 启动智能体$/ }));
    await waitFor(() => expect(agentCenterMocks.createAgentRun).toHaveBeenCalled());
    expect(agentCenterMocks.createAgentRun.mock.calls[0][0].step_by_step).toBe(true);
    expect(await screen.findByText(/已开启逐步确认/)).toBeInTheDocument();
  });

  it("surfaces contract validation errors inline", async () => {
    agentCenterMocks.createAgentRun.mockRejectedValue({
      response: { data: { detail: { code: "AGENT_RUN_GUIDANCE_INVALID", errors: [{ loc: ["analysis"] }] } } },
    });
    renderWizard();
    fireEvent.change(await screen.findByLabelText("选择项目"), { target: { value: "p1" } });
    fireEvent.change(await screen.findByLabelText("选择数据集"), { target: { value: "d1" } });
    await waitFor(() => expect(screen.getByLabelText("选择目标列").querySelectorAll("option").length).toBeGreaterThan(1));
    for (let i = 0; i < 4; i += 1) {
      fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    }
    fireEvent.click(await screen.findByRole("button", { name: /^rocket 启动智能体$/ }));
    expect(await screen.findByText(/AGENT_RUN_GUIDANCE_INVALID/)).toBeInTheDocument();
  });
});
