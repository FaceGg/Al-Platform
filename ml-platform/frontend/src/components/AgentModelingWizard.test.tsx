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
      dtypes: { ACTUAL_TORQUE: "float64", TARGET_TORQUE: "float64", "DECIDE(判定（最终判定）（0-不合格，1-合格）)": "int64" },
      preview: [],
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

    // Step 2: 数据形态单选已退役；列级数据类型默认自动预填（本例全部表格）。
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));

    // Step 3: 白名单默认全勾（用户指示）；点 LightGBM 取消勾选来收窄。
    const lightgbmInput = (await screen.findByText("LightGBM")).closest("label")?.querySelector("input");
    expect(lightgbmInput).toBeChecked();
    fireEvent.click(await screen.findByText("LightGBM"));
    expect(lightgbmInput).not.toBeChecked();
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
    expect(payload.guidance.feature.column_shapes).toEqual({
      ACTUAL_TORQUE: "tabular",
      TARGET_TORQUE: "tabular",
    });
    expect(payload.guidance.feature.data_shape).toBeUndefined();
    expect(payload.guidance.modeling.algorithm_whitelist).toEqual(["mlp"]);
    expect(payload.guidance.modeling.ensemble).toEqual({ enabled: false, top_k: 3 });
    expect(payload.guidance.evaluation.metric_gates).toEqual({});
  });

  it("previews the minority class as the error-backflow class on step 5", async () => {
    // 点焊形态：目标 1=缺陷（少数类）/0=正常——预览不得写死「0（不合格）」
    agentCenterMocks.fetchDatasetProfile.mockResolvedValueOnce({
      row_count: 10,
      column_count: 2,
      columns: [
        { name: "F1", base_name: "F1", semantic: null, missing_rate: 0, cardinality: 10, constant: false },
      ],
      mutual_info_top: [],
      target: { distribution: { "0": 9, "1": 1 }, imbalance_ratio: 9 },
    });
    renderWizard();
    fireEvent.change(await screen.findByLabelText("选择项目"), { target: { value: "p1" } });
    fireEvent.change(await screen.findByLabelText("选择数据集"), { target: { value: "d1" } });
    await waitFor(() => expect(screen.getByLabelText("选择目标列").querySelectorAll("option").length).toBeGreaterThan(1));
    await waitFor(() => expect(agentCenterMocks.fetchDatasetProfile).toHaveBeenCalled());
    for (let i = 0; i < 4; i += 1) {
      fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    }
    expect(await screen.findByText("将把「1」（少数类）判为报错回流")).toBeInTheDocument();
    expect(screen.queryByText(/将把「0」（不合格）/)).not.toBeInTheDocument();
  });

  it("sends ensemble config when weighted-voting training is enabled", async () => {
    renderWizard();
    fireEvent.change(await screen.findByLabelText("选择项目"), { target: { value: "p1" } });
    fireEvent.change(await screen.findByLabelText("选择数据集"), { target: { value: "d1" } });
    await waitFor(() => expect(screen.getByLabelText("选择目标列").querySelectorAll("option").length).toBeGreaterThan(1));
    for (let i = 0; i < 2; i += 1) {
      fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    }
    // 第三步启用集成学习并选前 2 名成员
    fireEvent.click(await screen.findByLabelText("启用集成学习"));
    fireEvent.change(screen.getByLabelText("集成成员数"), { target: { value: "2" } });
    for (let i = 0; i < 2; i += 1) {
      fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    }
    fireEvent.click(await screen.findByRole("button", { name: /^rocket 启动智能体$/ }));
    await waitFor(() => expect(agentCenterMocks.createAgentRun).toHaveBeenCalled());
    const payload = agentCenterMocks.createAgentRun.mock.calls[0][0];
    expect(payload.guidance.modeling.ensemble).toEqual({ enabled: true, top_k: 2 });
    // 白名单默认全勾（未动过）→ 全部算法进白名单
    expect(payload.guidance.modeling.algorithm_whitelist).toEqual(["lightgbm", "mlp"]);
  });

  it("auto-detects waveform columns structurally and honors manual override", async () => {
    // 波形是"这类列"而非固定列名：长编码串单元格（换名也能识别）判波形；
    // VIN 类短 ID 字符串列不误判。
    datasetMocks.getDatasetPreview.mockResolvedValue({
      columns: ["num1", "current_curve", "vin", "fault"],
      dtypes: { num1: "float64", current_curve: "object", vin: "object", fault: "int64" },
      preview: [
        { num1: 1.5, current_curve: "[" + "0.12,0.13,".repeat(120) + "0.14]", vin: "LFV2A21J8E4100001" },
        { num1: 2.5, current_curve: "[" + "0.22,0.23,".repeat(120) + "0.24]", vin: "LFV2A21J8E4100002" },
      ],
    });
    renderWizard();
    fireEvent.change(await screen.findByLabelText("选择项目"), { target: { value: "p1" } });
    fireEvent.change(await screen.findByLabelText("选择数据集"), { target: { value: "d1" } });
    await waitFor(() => expect(screen.getByLabelText("选择目标列").querySelectorAll("option").length).toBeGreaterThan(1));

    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    // 长编码串列（名字不含"波形"）判波形；短 ID 列保持表格。
    expect(await screen.findByLabelText("数据分类 current_curve")).toHaveValue("waveform");
    expect(screen.getByLabelText("数据分类 vin")).toHaveValue("tabular");
    expect(screen.getByLabelText("数据分类 num1")).toHaveValue("tabular");
    // 波形列的数据类型附注编码含义；短 ID 列是纯 string。
    const rowText = (column: string) =>
      screen.getByLabelText(`数据分类 ${column}`).closest("tr")?.textContent ?? "";
    expect(rowText("current_curve")).toContain("波形编码");
    expect(rowText("vin")).not.toContain("波形编码");
    // 用户手改波形列为表格：提交载荷以手改值为准。
    fireEvent.change(screen.getByLabelText("数据分类 current_curve"), { target: { value: "tabular" } });
    expect(rowText("current_curve")).not.toContain("波形编码");

    for (let i = 0; i < 3; i += 1) {
      fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    }
    fireEvent.click(await screen.findByRole("button", { name: /^rocket 启动智能体$/ }));
    await waitFor(() => expect(agentCenterMocks.createAgentRun).toHaveBeenCalled());
    const payload = agentCenterMocks.createAgentRun.mock.calls[0][0];
    expect(payload.guidance.feature.column_shapes).toEqual({
      num1: "tabular",
      current_curve: "tabular",
      vin: "tabular",
    });
  });

  it("shows all non-target columns without the 30-row cap and filters display only", async () => {
    const many = Array.from({ length: 40 }, (_, i) => `COL_${i + 1}`);
    datasetMocks.getDatasetPreview.mockResolvedValue({
      columns: [...many, "fault"],
      dtypes: Object.fromEntries([...many, "fault"].map((c) => [c, "float64"])),
      preview: [],
    });
    renderWizard();
    fireEvent.change(await screen.findByLabelText("选择项目"), { target: { value: "p1" } });
    fireEvent.change(await screen.findByLabelText("选择数据集"), { target: { value: "d1" } });
    await waitFor(() => expect(screen.getByLabelText("选择目标列").querySelectorAll("option").length).toBeGreaterThan(1));

    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    // 30 列上限已退役：第 31-40 列同样渲染。
    expect(await screen.findByLabelText("数据分类 COL_31")).toBeInTheDocument();
    expect(screen.getByLabelText("数据分类 COL_40")).toBeInTheDocument();
    // 筛选只影响显示：搜 COL_31 精确命中，载荷仍全量。
    fireEvent.change(screen.getByLabelText("筛选列"), { target: { value: "COL_31" } });
    expect(screen.queryByLabelText("数据分类 COL_1")).not.toBeInTheDocument();
    expect(screen.getByLabelText("数据分类 COL_31")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("筛选列"), { target: { value: "" } });

    for (let i = 0; i < 3; i += 1) {
      fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    }
    fireEvent.click(await screen.findByRole("button", { name: /^rocket 启动智能体$/ }));
    await waitFor(() => expect(agentCenterMocks.createAgentRun).toHaveBeenCalled());
    const payload = agentCenterMocks.createAgentRun.mock.calls[0][0];
    expect(Object.keys(payload.guidance.feature.column_shapes)).toHaveLength(40);
    expect(payload.guidance.feature.column_shapes["COL_40"]).toBe("tabular");
  });

  it("adds select-all to step 1, shows dtype column, and skips unknown classes in payload", async () => {
    datasetMocks.getDatasetPreview.mockResolvedValue({
      columns: ["num_int", "num_float", "ts", "mystery", "fault"],
      // mystery 故意不给 dtype 也不给样例 → 数据类型/数据分类均「未知」
      dtypes: { num_int: "int64", num_float: "float64", ts: "datetime64[ns]" },
      preview: [{ num_int: 1, num_float: 1.5, ts: "2026-01-01 08:00:00" }],
    });
    renderWizard();
    fireEvent.change(await screen.findByLabelText("选择项目"), { target: { value: "p1" } });
    fireEvent.change(await screen.findByLabelText("选择数据集"), { target: { value: "d1" } });
    await waitFor(() => expect(screen.getByLabelText("选择目标列").querySelectorAll("option").length).toBeGreaterThan(1));

    // 第一步全选：点一次全勾，再点一次全清。
    const selectAll = screen.getByLabelText("全选列");
    fireEvent.click(selectAll);
    expect(screen.getByLabelText("select num_int")).toBeChecked();
    expect(screen.getByLabelText("select mystery")).toBeChecked();
    fireEvent.click(selectAll);
    expect(screen.getByLabelText("select num_int")).not.toBeChecked();

    // 数据类型列按预览自动分析：int / float / 日期 / 未知。
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    const rowText = (column: string) =>
      screen.getByLabelText(`数据分类 ${column}`).closest("tr")?.textContent ?? "";
    expect(await screen.findByLabelText("数据分类 num_int")).toBeInTheDocument();
    expect(rowText("num_int")).toContain("int");
    expect(rowText("num_float")).toContain("float");
    expect(rowText("ts")).toContain("日期");
    expect(rowText("mystery")).toContain("未知");

    for (let i = 0; i < 3; i += 1) {
      fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    }
    fireEvent.click(await screen.findByRole("button", { name: /^rocket 启动智能体$/ }));
    await waitFor(() => expect(agentCenterMocks.createAgentRun).toHaveBeenCalled());
    const payload = agentCenterMocks.createAgentRun.mock.calls[0][0];
    // 未知列不进 column_shapes（对 S2 无信息量），目标列排除。
    expect(payload.guidance.feature.column_shapes).toEqual({
      num_int: "tabular",
      num_float: "tabular",
      ts: "tabular",
    });
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
