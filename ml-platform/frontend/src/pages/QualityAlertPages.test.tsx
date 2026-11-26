import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { LangProvider } from "../i18n";
import { ThemeProvider } from "../stores/themeContext";
import { App as AntApp } from "antd";

const mocks = vi.hoisted(() => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({
  default: mocks.apiClient,
  formatApiError: vi.fn((_e: unknown, fallback: string) => fallback),
}));

// jsdom 没有画布：图表替身只占位，断言「渲染了图」即可
vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="waveform-chart" />,
}));

import QualityAlertsPage from "./QualityAlertsPage";
import QualityDispositionPage from "./QualityDispositionPage";
import QualitySopsPage from "./QualitySopsPage";

const FUTURE = "2099-01-01T00:00:00";
const PAST = "2000-01-01T00:00:00";

function alertRow(overrides: Record<string, unknown> = {}) {
  return {
    id: "a1", project_id: "p1", scene_id: "s1", station_id: "st1", device_id: null,
    condition_value: null, source_type: "model_risk", risk_score: 0.99, severity: "critical",
    title: "模型风险：probability=0.990 越过触发阈值", sample_key: "VIN-001", batch_no: "B1",
    product_code: null,
    evidence: { kind: "model_risk", score_kind: "probability", score: 0.99, trigger_threshold: 0.7, rule: "threshold" },
    status: "open", assigned_to: null, first_ack_at: null, closed_at: null,
    sla_due_at: FUTURE, sla_notify_level: 0, resolution: null, occurrence_count: 1,
    merge_key: "model_risk:deployment=None", merge_open: true, last_event_at: FUTURE,
    is_demo: false, created_at: "2026-11-26T09:00:00",
    ...overrides,
  };
}

const alertDetail = (overrides: Record<string, unknown> = {}, events: unknown[] = []) => ({
  ...alertRow(overrides),
  events,
  allowed_transitions: overrides.allowed_transitions ?? ["acknowledged"],
});

function detailUrl(id: string) {
  return `/projects/p1/quality-alerts/${id}`;
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}{location.search}</div>;
}

function renderPage(node: React.ReactElement, initialEntries = ["/"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <LangProvider><ThemeProvider><AntApp>{node}<LocationProbe /></AntApp></ThemeProvider></LangProvider>
    </MemoryRouter>,
  );
}

/** 通用的 GET 路由：项目、场景、工位、成员，其余由各用例覆盖。 */
function baseGetRouter(overrides: Record<string, (config: { params?: Record<string, unknown> }) => unknown> = {}) {
  return (url: string, config: { params?: Record<string, unknown> } = {}) => {
    if (url in overrides) return Promise.resolve({ data: overrides[url](config) });
    if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "p1", name: "项目一" }] } });
    if (url === "/projects/p1/quality-scenes") {
      return Promise.resolve({ data: { items: [{ id: "s1", code: "S1", name: "场景一", field_roles: {} }] } });
    }
    if (url === "/projects/p1/quality-stations") {
      return Promise.resolve({ data: { items: [{ id: "st1", code: "ST1", name: "工位一", scene_id: "s1", enabled: true }] } });
    }
    if (url === "/projects/p1/members" || url === "/projects/p1/notification-recipients") {
      return Promise.resolve({ data: { items: [{ user_id: "u9", username: "张三", role: "operator" }], total: 1 } });
    }
    if (url === "/auth/me") return Promise.resolve({ data: { id: "me", username: "我", role: "owner" } });
    return Promise.resolve({ data: {} });
  };
}

/** 列表接口：按 status 过滤测试数据，page_size=1 时只回总数（摘要卡）。 */
function alertListRouter(rows: Record<string, unknown>[]) {
  return ({ params = {} }: { params?: Record<string, unknown> }) => {
    const filtered = rows.filter((row) => !params.status || row.status === params.status);
    const pageSize = Number(params.page_size ?? 20);
    return {
      items: pageSize === 1 ? [] : filtered.slice(0, pageSize),
      total: filtered.length, page: 1, page_size: pageSize,
    };
  };
}

async function pickSelectOption(label: string, optionText: string) {
  const combobox = await screen.findByRole("combobox", { name: label });
  fireEvent.mouseDown(combobox);
  // 选项文案可能与表格里的同名文字重复：只在下拉浮层里找
  await waitFor(() => {
    const option = Array.from(document.querySelectorAll(".ant-select-item-option"))
      .find((node) => node.textContent === optionText);
    if (!option) throw new Error(`option "${optionText}" not rendered`);
    fireEvent.click(option);
  });
}

function dialogOkButton(name: RegExp) {
  const dialog = screen.getByRole("dialog");
  const button = within(dialog).getAllByRole("button")
    .find((candidate) => name.test(candidate.textContent ?? ""));
  if (!button) throw new Error(`dialog button ${name} not found`);
  return button;
}

const CREATED_EVENT = {
  id: "e0", alert_id: "a1", action: "created", from_status: null, to_status: null,
  actor: null, note: null, form_snapshot: null, snapshot: null, created_at: "2026-11-26T09:00:00",
};

describe("QualityAlertsPage（预警中心）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation(baseGetRouter({
      "/projects/p1/quality-alerts": alertListRouter([
        alertRow({ occurrence_count: 3 }),
        alertRow({ id: "a2", title: "参数超限：force=12 超上限", source_type: "param_exceed", severity: "high",
          status: "acknowledged", assigned_to: "u9", sla_due_at: PAST, occurrence_count: 1,
          evidence: { kind: "param_exceed", field: "force", recorded_value: 12, spec: { usl: 8, lsl: 2, unit: "kN" } } }),
      ]),
    }));
  });

  it("lists alerts with severity, merged count, assignee and SLA state", async () => {
    renderPage(<QualityAlertsPage />);
    expect(await screen.findByText(/模型风险：probability=0.990/)).toBeInTheDocument();
    expect(screen.getByText("严重")).toBeInTheDocument();
    expect(screen.getByText("模型风险", { selector: ".ant-tag" })).toBeInTheDocument();
    expect(screen.getByText("同因 ×3")).toBeInTheDocument();
    // 责任人为空以醒目方式提示；已指派的显示姓名；SLA 超时有标记
    expect(screen.getByText("未指定")).toBeInTheDocument();
    expect(screen.getAllByText("张三").length).toBeGreaterThan(0);
    expect(screen.getByText(/^超时 /)).toBeInTheDocument();
    // 诚实设计②：风险分口径脚注在位
    expect(screen.getByTestId("risk-footnote")).toHaveTextContent("触发下限独立于分级阈值");
    await waitFor(() => expect(mocks.apiClient.get).toHaveBeenCalledWith(
      "/projects/p1/quality-alerts", expect.objectContaining({ params: expect.objectContaining({ sla_overdue: "true", page_size: 1 }) }),
    ));
  });

  it("acknowledge stays disabled until an assignee is chosen", async () => {
    renderPage(<QualityAlertsPage />);
    const trigger = await screen.findByTestId("ack-a1");
    expect(screen.getByTestId("batch-ack")).toBeDisabled();
    fireEvent.click(trigger);
    const ok = await waitFor(() => dialogOkButton(/^确\s*认$/));
    expect(ok).toBeDisabled();
    await pickSelectOption("批量确认责任人", "张三");
    await waitFor(() => expect(dialogOkButton(/^确\s*认$/)).toBeEnabled());
    fireEvent.click(dialogOkButton(/^确\s*认$/));
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith(
      "/projects/p1/quality-alerts/a1/ack", { assignee_id: "u9", note: undefined },
    ));
  });

  it("batch acknowledge only offers open alerts", async () => {
    renderPage(<QualityAlertsPage />);
    await screen.findByText(/模型风险：probability=0.990/);
    const checkboxes = screen.getAllByRole("checkbox");
    // 第一个是表头全选；a1（待确认）可选，a2（已确认）不可选
    expect(checkboxes[2]).toBeDisabled();
    fireEvent.click(checkboxes[1]);
    await waitFor(() => expect(screen.getByTestId("batch-ack")).toBeEnabled());
    expect(screen.getByTestId("batch-ack")).toHaveTextContent("批量确认（1）");
  });

  it("hands an alert over to the disposition workbench by id", async () => {
    renderPage(<QualityAlertsPage />);
    fireEvent.click(await screen.findByTestId("open-a1"));
    await waitFor(() => expect(screen.getByTestId("location-probe")).toHaveTextContent("/quality/disposition?alert=a1"));
  });

  it("keeps demo alerts hidden unless the demo switch is on", async () => {
    renderPage(<QualityAlertsPage />);
    await screen.findByText(/模型风险：probability=0.990/);
    const listCalls = () => mocks.apiClient.get.mock.calls.filter(([url]) => url === "/projects/p1/quality-alerts");
    expect(listCalls().some(([, config]) => config?.params?.page_size === 20 && config.params.include_demo === undefined)).toBe(true);
    fireEvent.click(screen.getByRole("switch", { name: "显示演示数据" }));
    await waitFor(() => expect(listCalls().some(([, config]) => config?.params?.include_demo === "true")).toBe(true));
  });
});

const CRITERIA = [
  { criterion: "spec_exceed", status: "skipped", detail: "该字段无规格定义，或预警无字段/数值上下文" },
  { criterion: "sigma_3", status: "skipped", detail: "未冻结基线，仅规格判据可用" },
  { criterion: "sigma_2", status: "skipped", detail: "未冻结基线，仅规格判据可用" },
  { criterion: "baseline_deviation_30", status: "skipped", detail: "未冻结基线，仅规格判据可用" },
];

describe("QualityDispositionPage（处置工作台）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
  });

  function mockDetail(overrides: Record<string, unknown> = {}, events: unknown[] = []) {
    mocks.apiClient.get.mockImplementation(baseGetRouter({
      "/projects/p1/quality-alerts": alertListRouter([alertRow(overrides)]),
      [detailUrl("a1")]: () => alertDetail(overrides, events),
      [detailUrl("a1") + "/criteria"]: () => ({ criteria: CRITERIA }),
      [detailUrl("a1") + "/waveform"]: () => ({ status: "no_waveform", reason: "预警无样本键，无法定位波形" }),
    }));
  }

  it("opens the alert from the query string and shows evidence, criteria and the assignee guard", async () => {
    mockDetail({ sample_key: null }, [CREATED_EVENT]);
    renderPage(<QualityDispositionPage />, ["/quality/disposition?alert=a1"]);
    expect(await screen.findByTestId("alert-evidence")).toBeInTheDocument();
    expect(screen.getByTestId("alert-evidence")).toHaveTextContent("预测概率 0.99");
    expect(screen.getByTestId("alert-evidence")).toHaveTextContent("未冻结基线");
    // 判据链四条齐全；无基线时 σ 类判据显式不适用并给出提示
    expect(within(screen.getByTestId("alert-criteria")).getAllByText("不适用")).toHaveLength(4);
    expect(screen.getByTestId("alert-criteria")).toHaveTextContent("未冻结基线");
    // 诚实设计③：没有波形时说明原因
    expect(screen.getByTestId("alert-waveform")).toHaveTextContent("暂无波形：预警无样本键");
    // 确认防呆：未选责任人时确认不可用
    expect(screen.getByTestId("alert-ack")).toBeDisabled();
    // NCR 入口预留但未启用
    expect(screen.getByRole("button", { name: /登记 NCR/ })).toBeDisabled();
    // 轨迹可读
    expect(screen.getByTestId("alert-trail")).toHaveTextContent("产生预警");
  });

  it("walks an alert from acknowledgement to a submitted disposition", async () => {
    let current = { status: "open", allowed_transitions: ["acknowledged"] };
    mocks.apiClient.get.mockImplementation(baseGetRouter({
      "/projects/p1/quality-alerts": alertListRouter([alertRow()]),
      [detailUrl("a1")]: () => alertDetail(current, [
        { id: "e1", alert_id: "a1", action: "created", from_status: null, to_status: null, actor: null, note: null, form_snapshot: null, snapshot: null, created_at: "2026-11-26T09:00:00" },
      ]),
      [detailUrl("a1") + "/criteria"]: () => ({ criteria: CRITERIA }),
      [detailUrl("a1") + "/waveform"]: () => ({ status: "no_waveform", reason: "预警无样本键，无法定位波形" }),
    }));
    mocks.apiClient.post.mockImplementation(async (url: string) => {
      if (url.endsWith("/ack")) current = { status: "acknowledged", allowed_transitions: ["processing", "review_pending", "closed"] };
      if (url.endsWith("/transition")) current = { status: "processing", allowed_transitions: ["review_pending", "closed"] };
      return { data: alertDetail(current) };
    });
    renderPage(<QualityDispositionPage />, ["/quality/disposition?alert=a1"]);
    await screen.findByTestId("alert-ack");

    // 确认：先选责任人
    await pickSelectOption("责任人", "张三");
    fireEvent.click(screen.getByTestId("alert-ack"));
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith(
      detailUrl("a1") + "/ack", { assignee_id: "u9", note: undefined },
    ));
    // 已确认 → 开始处理
    fireEvent.click(await screen.findByTestId("alert-start"));
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith(
      detailUrl("a1") + "/transition", { to_status: "processing", note: undefined, resolution: undefined },
    ));
    // 处理中 → 处置表单；确认为真实异常必须填原因与措施
    const form = await screen.findByTestId("disposition-form");
    const textareas = within(form).getAllByPlaceholderText("确认异常时必填");
    fireEvent.change(textareas[0], { target: { value: "电极磨损" } });
    fireEvent.change(textareas[1], { target: { value: "更换电极并复检" } });
    fireEvent.click(within(form).getByRole("button", { name: /提交处置并关闭/ }));
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith(
      detailUrl("a1") + "/disposition",
      expect.objectContaining({ resolution: "confirmed_issue", cause: "电极磨损", action: "更换电极并复检" }),
    ));
  });

  it("shows a closed alert read-only with its frozen disposition", async () => {
    mockDetail(
      { status: "closed", resolution: "confirmed_issue", allowed_transitions: [] },
      [{
        id: "e2", alert_id: "a1", action: "disposition_submitted", from_status: "processing", to_status: "closed",
        actor: "u1", note: null, created_at: "2026-11-26T10:00:00",
        form_snapshot: { type: "设备维修", cause: "电极磨损", action: "更换电极", downtime: true, rework: false, expanded_inspection: false },
        snapshot: { sops: [{ code: "SOP-A", version: 1 }], spc_baseline: null, model_version: null, criteria: [] },
      }],
    );
    renderPage(<QualityDispositionPage />, ["/quality/disposition?alert=a1"]);
    const summary = await screen.findByTestId("disposition-summary");
    expect(summary).toHaveTextContent("处置结论：确认异常");
    expect(summary).toHaveTextContent("更换电极");
    expect(screen.queryByTestId("alert-actions")).not.toBeInTheDocument();
    expect(screen.queryByTestId("disposition-form")).not.toBeInTheDocument();
  });

  it("overlays the waveform with the spec target window when a sample is available", async () => {
    mocks.apiClient.get.mockImplementation(baseGetRouter({
      [detailUrl("a1")]: () => alertDetail({}),
      [detailUrl("a1") + "/criteria"]: () => ({ criteria: CRITERIA }),
      [detailUrl("a1") + "/waveform"]: () => ({
        status: "ok", column: "cvei", points: [1, 5, 3], dataset_version_id: "v1",
        specs: [{ statistic: "mean", target: 120, usl: 200, lsl: 50, unit: "A" }],
      }),
    }));
    renderPage(<QualityDispositionPage />, ["/quality/disposition?alert=a1"]);
    expect(await screen.findByTestId("waveform-chart")).toBeInTheDocument();
  });

  it("exports an evidence package for the alert", async () => {
    URL.createObjectURL = vi.fn(() => "blob:evidence");
    URL.revokeObjectURL = vi.fn();
    mocks.apiClient.post.mockResolvedValue({
      data: { artifact_id: "e1", name: "evidence-alert.zip", file_size: 10, sha256: "x", file_count: 5, include_audit: false },
    });
    mockDetail({ status: "closed", resolution: "confirmed_issue", allowed_transitions: [] }, [CREATED_EVENT]);
    renderPage(<QualityDispositionPage />, ["/quality/disposition?alert=a1"]);
    await screen.findByTestId("alert-trail");
    fireEvent.click(screen.getByTestId("alert-export-evidence"));
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith(
      "/projects/p1/evidence-exports", { scope: "alert", target_id: "a1" },
    ));
    await waitFor(() => expect(mocks.apiClient.get).toHaveBeenCalledWith(
      "/projects/p1/evidence-exports/e1/download", expect.objectContaining({ responseType: "blob" }),
    ));
  });
});

describe("QualitySopsPage（SOP 维护）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation(baseGetRouter({
      "/projects/p1/quality-sops": () => ({ items: [
        { id: "sop1", project_id: "p1", scene_id: "s1", code: "SOP-A", version: 2, title: "电极更换（修订）",
          content: { spec_exceed: ["停机", "更换电极"], spc_exceed: [], ai_risk: [] }, condition_value: null,
          effective_from: "2026-11-26T08:00:00", retired_at: null, is_active: true },
        { id: "sop2", project_id: "p1", scene_id: "s1", code: "SOP-A", version: 1, title: "电极更换",
          content: { spec_exceed: ["停机"], spc_exceed: [], ai_risk: [] }, condition_value: null,
          effective_from: "2026-11-20T08:00:00", retired_at: "2026-11-26T08:00:00", is_active: false },
      ], total: 2 }),
      "/projects/p1/dataset-versions": () => ({ items: [
        { id: "v1", project_id: "p1", source_name: "weld.csv", version: 3, status: "ready", row_count: 500, column_count: 2,
          columns: [{ name: "force", dtype: "float64", nullable: false, position: 0 }] },
      ] }),
      "/projects/p1/quality-scenes/s1/alert-settings": () => ({
        alert_settings: {}, resolved: { trigger_threshold: 0.7, high_threshold: 0.85, critical_threshold: 0.95, sla_hours: 24, merge_window_minutes: 30 },
      }),
    }));
  });

  it("lists SOP versions with retired ones kept", async () => {
    renderPage(<QualitySopsPage />);
    expect(await screen.findByText("电极更换（修订）")).toBeInTheDocument();
    expect(screen.getByText("电极更换")).toBeInTheDocument();
    expect(screen.getByText("生效中")).toBeInTheDocument();
    expect(screen.getByText("已退役")).toBeInTheDocument();
  });

  it("creates a new SOP version with guidance split per line", async () => {
    mocks.apiClient.post.mockResolvedValue({ data: { id: "sop3", version: 1 } });
    renderPage(<QualitySopsPage />);
    fireEvent.click(await screen.findByTestId("new-sop"));
    const form = await screen.findByTestId("sop-form");
    fireEvent.change(within(form).getByPlaceholderText("SOP-A"), { target: { value: "SOP-B" } });
    const textInputs = within(form).getAllByRole("textbox");
    fireEvent.change(textInputs[1], { target: { value: "来料检查" } });
    const textareas = within(form).getAllByRole("textbox").filter((node) => node.tagName === "TEXTAREA");
    fireEvent.change(textareas[0], { target: { value: "停机检查\n更换电极" } });
    fireEvent.click(dialogOkButton(/^创\s*建$/));
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith(
      "/projects/p1/quality-sops",
      expect.objectContaining({
        code: "SOP-B", title: "来料检查",
        content: expect.objectContaining({ spec_exceed: ["停机检查", "更换电极"] }),
      }),
    ));
  });

  it("loads alert rules with platform defaults and saves only the overridden keys", async () => {
    mocks.apiClient.put.mockResolvedValue({ data: { alert_settings: { trigger_threshold: 0.5 }, resolved: {} } });
    renderPage(<QualitySopsPage />, ["/quality/sops?tab=rules"]);
    expect(await screen.findByTestId("rules-defaults")).toHaveTextContent("触发 0.7");
    const form = await screen.findByTestId("rules-form");
    const firstNumber = within(form).getAllByRole("spinbutton")[0];
    fireEvent.change(firstNumber, { target: { value: "0.5" } });
    fireEvent.click(screen.getByTestId("save-rules"));
    await waitFor(() => expect(mocks.apiClient.put).toHaveBeenCalledWith(
      "/projects/p1/quality-scenes/s1/alert-settings",
      expect.objectContaining({ trigger_threshold: 0.5 }),
    ));
    const body = mocks.apiClient.put.mock.calls[0][1] as Record<string, unknown>;
    expect(body.high_threshold).toBeUndefined();
  });

  it("freezes a baseline from a dataset version window", async () => {
    mocks.apiClient.post.mockResolvedValue({ data: { id: "b1", version: 1 } });
    renderPage(<QualitySopsPage />, ["/quality/sops?tab=baselines"]);
    await screen.findByRole("tab", { name: "SPC 基线" });
    fireEvent.click(await screen.findByTestId("freeze-baseline"));
    const form = await screen.findByTestId("baseline-form");
    await pickSelectOption("数据集版本", "v3 · weld.csv · 500 行");
    await pickSelectOption("过程参数（字段）", "force（float64）");
    fireEvent.change(within(form).getAllByRole("spinbutton")[0], { target: { value: "0" } });
    fireEvent.change(within(form).getAllByRole("spinbutton")[1], { target: { value: "29" } });
    fireEvent.click(dialogOkButton(/^冻\s*结$/));
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith(
      "/projects/p1/quality-scenes/s1/spc-baselines",
      expect.objectContaining({ dataset_version_id: "v1", field: "force", row_index_from: 0, row_index_to: 29 }),
    ));
  });
});
