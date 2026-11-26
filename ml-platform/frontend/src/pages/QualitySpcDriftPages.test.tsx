import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LangProvider } from "../i18n";
import { ThemeProvider } from "../stores/themeContext";
import { App as AntApp } from "antd";

const mocks = vi.hoisted(() => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../api/client", () => ({
  default: mocks.apiClient,
  formatApiError: vi.fn((_e: unknown, fallback: string) => fallback),
}));

vi.mock("echarts-for-react", () => ({ default: () => <div data-testid="chart" /> }));

import QualitySpcPage from "./QualitySpcPage";
import DriftMonitorPage from "./DriftMonitorPage";

const SPC_BASE = "/projects/p1/spc";

const FIELDS = [
  { name: "force", dtype: "float64", numeric: true },
  { name: "vin", dtype: "string", numeric: false },
];

const ANALYSIS = {
  chart_kind: "i_mr", source: "dataset", field: "force",
  sample_count: 40, subgroup_size: null, subgroup_count: null,
  spec: { usl: 12.0, lsl: 9.0, target: 10.75, unit: "kN", source: "scene_spec" },
  charts: {
    i: {
      kind: "i", center: 10.75, ucl: 12.25, lcl: 9.25, sigma: 0.5,
      in_control_count: 39, in_control_rate: 39 / 40, notes: [],
      points: [
        { index: 0, value: 10.0, violations: [], ucl: null, lcl: null, sample_key: "spc-0", occurred_at: null },
        { index: 39, value: 20.0, violations: [1], ucl: null, lcl: null, sample_key: "spc-39", occurred_at: null },
      ],
    },
    mr: {
      kind: "mr", center: 0.5, ucl: 1.63, lcl: 0, sigma: 0.5,
      in_control_count: 39, in_control_rate: 39 / 40, notes: [],
      points: [{ index: 0, value: 0.5, violations: [], ucl: null, lcl: null, sample_key: "spc-0", occurred_at: null }],
    },
  },
  capability: {
    count: 40, mean: 10.75, usl: 12, lsl: 9, target: 10.75,
    within_sigma: 0.5, overall_sigma: 0.9, within_sigma_source: "baseline",
    cp: 1.0, cpk: 1.0, pp: 0.56, ppk: 0.46, cpm: 1.0, cr: 1.0,
    sigma_level: 3.1, ppm: 150,
  },
  histogram: { edges: [9, 10.5, 12, 13.5], counts: [30, 9, 1] },
  violations: [
    { chart: "i", rule: 1, index: 39, value: 20.0, sample_key: "spc-39", occurred_at: null },
  ],
  violation_count: 1, alerts_raised: 0, notes: ["组内 σ 取自冻结基线 v2（中心 10.75，σ 0.5）"],
  generated_at: "2026-11-26T12:00:00",
};

const DEPLOYMENTS = [
  { id: "d1", name: "主力部署", model_version_id: "v1", has_baseline: true,
    latest: { id: "r1", level: "severe", sample_count: 5000,
      summary: { signal_counts: { feature_psi: 2, dq_missing: 1 } }, proposal_at: null } },
  { id: "d2", name: "外部导入部署", model_version_id: "v2", has_baseline: false, latest: null },
];

const REPORTS = [
  { id: "r1", deployment_id: "d1", deployment_name: "主力部署", level: "severe", sample_count: 5000,
    summary: { signal_counts: { feature_psi: 2 } }, proposal_at: null, created_at: "2026-11-26T12:00:00",
    started_at: "2026-11-25T12:00:00", ended_at: "2026-11-26T12:00:00" },
];

const REPORT_DETAIL = {
  ...REPORTS[0], project_id: "p1", model_version_id: "v1",
  features: [
    { feature_name: "force", signal_kind: "feature_psi", value: 0.41, threshold: 0.25, level: "severe",
      detail: { observed_shares: [0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.6] } },
  ],
  not_wired: ["pca_reconstruction_error", "score_psi_in_report", "per_shard_buckets"],
};

function renderPage(node: React.ReactElement, initialEntries = ["/"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <LangProvider><ThemeProvider><AntApp>{node}</AntApp></ThemeProvider></LangProvider>
    </MemoryRouter>,
  );
}

function router(overrides: Record<string, unknown> = {}) {
  return (url: string) => {
    if (url in overrides) return Promise.resolve({ data: overrides[url] });
    if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "p1", name: "项目一" }] } });
    if (url === "/projects/p1/quality-scenes") return Promise.resolve({ data: { items: [{ id: "s1", code: "S1", name: "场景一", field_roles: {} }] } });
    if (url === "/projects/p1/quality-stations") return Promise.resolve({ data: { items: [] } });
    if (url === "/projects/p1/members" || url === "/projects/p1/notification-recipients") {
      return Promise.resolve({ data: { items: [{ user_id: "u9", username: "张三", role: "operator" }], total: 1 } });
    }
    if (url === "/projects/p1/dataset-versions") {
      return Promise.resolve({ data: { items: [{ id: "v1", project_id: "p1", source_name: "weld.csv", version: 3, status: "ready", row_count: 5000, column_count: 2 }] } });
    }
    if (url === `${SPC_BASE}/fields`) return Promise.resolve({ data: { fields: FIELDS } });
    if (url === "/projects/p1/drift/deployments") return Promise.resolve({ data: { items: DEPLOYMENTS, scan_interval_seconds: 300 } });
    if (url === "/projects/p1/drift/reports") return Promise.resolve({ data: { items: REPORTS, total: 1, page: 1, page_size: 20 } });
    if (url === "/projects/p1/drift/reports/r1") return Promise.resolve({ data: REPORT_DETAIL });
    return Promise.resolve({ data: { items: [], total: 0 } });
  };
}

/** 在下拉浮层里按精确文字点选选项（选项文字常与表格内容撞名）。 */
async function pickOption(optionText: string) {
  await waitFor(() => {
    const option = Array.from(document.querySelectorAll(".ant-select-item-option"))
      .find((node) => node.textContent === optionText);
    if (!option) throw new Error(`option "${optionText}" not rendered`);
    fireEvent.click(option);
  });
}

describe("QualitySpcPage（SPC 过程控制）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    localStorage.setItem("role", "owner");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation(router());
    mocks.apiClient.post.mockResolvedValue({ data: ANALYSIS });
  });

  it("runs an analysis and renders the chart, capability, spec source and caliber notes", async () => {
    renderPage(<QualitySpcPage />);
    const run = await screen.findByTestId("spc-run");
    // 选择过程参数后再分析
    await waitFor(() => expect(mocks.apiClient.get).toHaveBeenCalledWith(
      `${SPC_BASE}/fields`, expect.objectContaining({ params: { source: "dataset", dataset_version_id: undefined } }),
    ));
    const combobox = screen.getAllByRole("combobox").find((node) => node.getAttribute("aria-label") === "过程参数");
    fireEvent.mouseDown(combobox!);
    await pickOption("force");
    fireEvent.click(run);
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith(
      `${SPC_BASE}/analyze`,
      // 「登记预警」开关默认关闭；载荷里的 raise_alerts 为 false
      expect.objectContaining({ source: "dataset", field: "force", chart: "i_mr", use_scene_spec: true, raise_alerts: false }),
    ));
    expect(await screen.findByTestId("spc-chart")).toBeInTheDocument();
    expect(screen.getByTestId("spc-violations")).toHaveTextContent("点越出 3σ");
    expect(screen.getByTestId("spc-violations")).toHaveTextContent("spc-39");
    // 诚实设计②：组内 σ 来源与能力指数在页面上
    expect(screen.getByTestId("spc-notes")).toHaveTextContent("组内 σ 取自冻结基线 v2");
    expect(screen.getByTestId("spc-footnote")).toHaveTextContent("Cp / Cpk 用组内标准差");
    // 能力指数按结果渲染（Cp 1.0 / Pp 0.56）
    expect(screen.getByText("Cp（组内）")).toBeInTheDocument();
    expect(screen.getByText("Pp（整体）")).toBeInTheDocument();
  });

  it("notes the overall-sigma fallback when there is no frozen baseline", async () => {
    mocks.apiClient.post.mockResolvedValue({ data: {
      ...ANALYSIS,
      capability: { ...ANALYSIS.capability, within_sigma_source: "overall", cp: 0.56 },
      notes: ["该字段没有冻结基线，也未按子群取数：组内 σ 由整体标准差估计，Cp / Cpk 实际等同于 Pp / Ppk，不代表过程能力"],
    } });
    renderPage(<QualitySpcPage />);
    const combobox = await waitFor(() => {
      const node = screen.getAllByRole("combobox").find((item) => item.getAttribute("aria-label") === "过程参数");
      if (!node) throw new Error("field combobox not ready");
      return node;
    });
    fireEvent.mouseDown(combobox);
    await pickOption("force");
    fireEvent.click(screen.getByTestId("spc-run"));
    expect(await screen.findByTestId("spc-notes")).toHaveTextContent("不代表过程能力");
  });
});

describe("DriftMonitorPage（漂移监控）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    localStorage.setItem("role", "owner");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation(router());
    mocks.apiClient.post.mockResolvedValue({ data: { scanned: 2, levels: { insufficient: 2 } } });
  });

  it("lists running deployments, honest no-baseline note and graded reports", async () => {
    renderPage(<DriftMonitorPage />, ["/algo/drift"]);
    expect(await screen.findByText("主力部署")).toBeInTheDocument();
    expect(screen.getByTestId("drift-no-baseline-note")).toHaveTextContent("无基线");
    // 最严重状态（统计卡）与信号计数（报告行）各出现一次「严重漂移」
    const severeTexts = await screen.findAllByText("严重漂移");
    expect(severeTexts.length).toBeGreaterThanOrEqual(1);
    const signals = screen.getAllByText(/特征分布漂移 ×2/);
    expect(signals.length).toBeGreaterThan(0);
    // 立即扫描（管理权限）
    fireEvent.click(screen.getByTestId("drift-scan"));
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith("/projects/p1/drift/scan"));
    expect(screen.getByTestId("drift-footnote")).toHaveTextContent("平台不自动重训或回滚");
  });

  it("shows the report detail with traces to the baseline and honest not-wired list", async () => {
    renderPage(<DriftMonitorPage />, ["/algo/drift"]);
    fireEvent.click(await screen.findByTestId("open-report-r1"));
    const features = await screen.findByTestId("drift-features");
    expect(features).toHaveTextContent("force");
    expect(features).toHaveTextContent("特征分布漂移");
    expect(screen.getByTestId("drift-not-wired")).toHaveTextContent("PCA 重构误差");
    expect(screen.getByTestId("drift-not-wired")).toHaveTextContent("分片部署按「版本 × 工况」分桶");
    // 未提交过提案 → 可提交
    expect(screen.getByTestId("propose-retrain")).toBeInTheDocument();
  });

  it("submits a retrain proposal once and hides the action after submission", async () => {
    // 详情按「是否已提交过提案」可变返回：提案前有按钮，提案后按钮消失
    let proposed = false;
    mocks.apiClient.get.mockImplementation((url: string) => {
      if (url === "/projects/p1/drift/reports/r1") {
        return Promise.resolve({ data: { ...REPORT_DETAIL, proposal_at: proposed ? "2026-11-26T12:30:00" : null } });
      }
      return router()(url);
    });
    mocks.apiClient.post.mockImplementation(async (url: string) => {
      if (url === "/projects/p1/drift/reports/r1/propose-retrain") {
        proposed = true;
        return { data: { proposal_at: "2026-11-26T12:30:00", notified: 1 } };
      }
      return Promise.resolve({ data: {} });
    });
    const first = renderPage(<DriftMonitorPage />, ["/algo/drift"]);
    fireEvent.click(await screen.findByTestId("open-report-r1"));
    fireEvent.click(await screen.findByTestId("propose-retrain"));
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith(
      "/projects/p1/drift/reports/r1/propose-retrain",
    ));
    // 提交后弹窗里不再有提交按钮
    await waitFor(() => expect(screen.queryByTestId("propose-retrain")).not.toBeInTheDocument());
    // 卸载第一个实例再测操作员视角：否则旧弹窗仍挂在文档里干扰查询
    first.unmount();
    localStorage.setItem("role", "operator");
    renderPage(<DriftMonitorPage />, ["/algo/drift"]);
    await screen.findByText("主力部署");
    expect(screen.queryByTestId("drift-scan")).not.toBeInTheDocument();
  });
});
