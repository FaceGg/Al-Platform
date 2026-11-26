import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
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

import QualityDashboardPage from "./QualityDashboardPage";
import QualityMonitorPage from "./QualityMonitorPage";
import QualityTrendsPage from "./QualityTrendsPage";
import QualityAlertsPage from "./QualityAlertsPage";
import { parseSseChunk, subscribeMonitorStream } from "../api/qualityMonitor";

const MONITOR = "/projects/p1/quality-monitor";

const STATIONS = [
  { id: "st1", scene_id: "s1", code: "ST1", name: "甲工位", enabled: true, production_line: "L1", factory: "F1", workshop: "W1", edge_device_id: null, responsible_user_id: null },
  { id: "st2", scene_id: "s1", code: "ST2", name: "乙工位", enabled: true, production_line: "L1", factory: "F1", workshop: "W1", edge_device_id: null, responsible_user_id: null },
];

const DASHBOARD = {
  scope: {}, window: { days: 7, since: "2026-11-20T00:00:00", until: "2026-11-26T10:00:00" },
  production: { total: 35, ok: 27, anomaly: 8 },
  alerts: {
    alerts_in_window: 5, open: 3, high_risk: 2, sla_overdue: 0, confirmed_ng: 3,
    closed_in_window: 2, by_severity: { warning: 3, high: 1, critical: 1 }, hit_rate: 0.5,
  },
  disposition_ops: {
    per_thousand: 57.14, mean_first_ack_seconds: 2400, acknowledged: 2,
    closure_rate: 0.4, closed_in_window: 2, created_in_window: 5,
  },
  trend: {
    points: [
      { date: "2026-11-25", total: 20, anomaly: 5, alerts: 2, high: 1, critical: 0, spc_exceed: 1, closed: 1, confirmed_ng: 1, ng_rate: 0.05 },
      { date: "2026-11-26", total: 15, anomaly: 3, alerts: 3, high: 0, critical: 1, spc_exceed: 0, closed: 1, confirmed_ng: 2, ng_rate: 0.1333 },
    ],
    totals: { total: 35, confirmed_ng: 3, ng_rate: 3 / 35, spc_exceed: 1 },
  },
  recent: [{ id: "a1", title: "模型风险：probability=0.990", severity: "critical", source_type: "model_risk", status: "open", created_at: "2026-11-26T09:00:00", station: "甲工位（ST1）", occurrence_count: 1 }],
  station_ranking: [{ station_id: "st1", station: "甲工位（ST1）", alerts: 4, open: 2, high_risk: 1, occurrences: 5 }],
  line_status: [{ line: "L1", stations: 2, stations_with_open_alerts: 1, offline_devices: 1 }],
  stale: { stale: false, last_production_at: "2026-11-26T09:00:00", hours: 1.2, never_produced: false },
};

const TRENDS = {
  scope: {}, window: DASHBOARD.window, trend: DASHBOARD.trend,
  pareto: { dimension: "defect", total: 3, items: [{ key: "spatter", label: "飞溅", count: 2, ratio: 2 / 3, cumulative: 2 / 3 }, { key: "p", label: "气孔", count: 1, ratio: 1 / 3, cumulative: 1 }] },
  ng_vocabulary: { spatter: "飞溅" }, stale: DASHBOARD.stale, generated_at: "2026-11-26T10:00:00",
};

const card = (overrides: Record<string, unknown>) => ({
  station_id: "st1", code: "ST1", name: "甲工位", scene: "场景一", factory: "F1", workshop: "W1", production_line: "L1",
  responsible_user_id: null, product: "P-1", batch: "B-9", shift: "早班", last_production_at: "2026-11-26T09:00:00",
  result: "anomaly", score: 0.91, predicted_label: null, shift_total: 12, shift_anomaly: 2, open_alerts: 1,
  latest_alert: { id: "a1", title: "模型风险：probability=0.990", severity: "high", status: "open", created_at: "2026-11-26T09:00:00" },
  device: { id: "d1", name: "焊机-1", status: "online", online: true, last_heartbeat: "2026-11-26T09:00:00" },
  ...overrides,
});

const STATIONS_PAYLOAD = {
  scope: {}, now: "2026-11-26T10:00:00", shift: { label: "早班", start: "2026-11-26T08:00:00" },
  cards: [card({}), card({ station_id: "st2", code: "ST2", name: "乙工位", open_alerts: 0, device: { id: "d2", name: "焊机-2", status: "online", online: false, last_heartbeat: null } })],
  tree: [{ key: "line:L1", title: "L1", children: [{ key: "st1", title: "甲工位（ST1）", open_alerts: 1, device: null }, { key: "st2", title: "乙工位（ST2）", open_alerts: 0, device: null }] }],
  stale: DASHBOARD.stale,
};

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

function router(overrides: Record<string, unknown> = {}) {
  return (url: string) => {
    if (url in overrides) return Promise.resolve({ data: overrides[url] });
    if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "p1", name: "项目一" }] } });
    if (url === "/projects/p1/quality-scenes") return Promise.resolve({ data: { items: [{ id: "s1", code: "S1", name: "场景一", field_roles: {} }] } });
    if (url === "/projects/p1/quality-stations") return Promise.resolve({ data: { items: STATIONS } });
    if (url === "/projects/p1/members" || url === "/projects/p1/notification-recipients") {
      return Promise.resolve({ data: { items: [{ user_id: "u9", username: "张三", role: "operator" }], total: 1 } });
    }
    if (url === `${MONITOR}/scope-options`) return Promise.resolve({ data: { factory: ["F1"], workshop: ["W1"], production_line: ["L1"] } });
    if (url === `${MONITOR}/dashboard`) return Promise.resolve({ data: DASHBOARD });
    if (url === `${MONITOR}/trends`) return Promise.resolve({ data: TRENDS });
    if (url === `${MONITOR}/stations`) return Promise.resolve({ data: STATIONS_PAYLOAD });
    if (url === "/auth/me") return Promise.resolve({ data: { id: "me", username: "我", role: "owner" } });
    return Promise.resolve({ data: { items: [], total: 0 } });
  };
}

describe("parseSseChunk", () => {
  it("splits complete frames and keeps the partial tail", () => {
    const first = parseSseChunk('data: {"type":"snapshot"}\n\n: keepalive\n\ndata: {"type":"al');
    expect(first.events).toEqual([{ type: "snapshot" }]);
    expect(first.rest).toBe('data: {"type":"al');
    const second = parseSseChunk(first.rest + 'erts"}\n\n');
    expect(second.events).toEqual([{ type: "alerts" }]);
    expect(second.rest).toBe("");
  });
});

describe("subscribeMonitorStream（推送流的流式读取路径）", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reads the response body stream, authenticates by header and falls back when the server ends the stream", async () => {
    localStorage.setItem("token", "test-token");
    const encoder = new TextEncoder();
    // 两段读取：第一段含一个完整帧和一个半截帧，第二段补全——验证跨块的半截帧不会丢
    const chunks = ['data: {"type":"snapshot"}\n\n: keepalive\n\nda', 'ta: {"type":"alerts"}\n\n'];
    const body = new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, body });
    vi.stubGlobal("fetch", fetchMock);
    const events: unknown[] = [];
    const onFallback = vi.fn();
    const stop = subscribeMonitorStream("p1", { factory: "F1" }, {
      onEvent: (event) => events.push(event),
      onFallback,
    });
    await waitFor(() => expect(events).toEqual([{ type: "snapshot" }, { type: "alerts" }]));
    // 服务端正常结束流之后应降级轮询，保证页面继续刷新
    await waitFor(() => expect(onFallback).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/projects/p1/quality-monitor/stream?factory=F1");
    // 鉴权走请求头，令牌不进 URL
    expect(fetchMock.mock.calls[0][1].headers).toEqual({ Authorization: "Bearer test-token" });
    expect(fetchMock.mock.calls[0][0]).not.toContain("test-token");
    stop();
  });
});

describe("QualityDashboardPage（质量驾驶舱）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation(router());
  });

  it("shows the six KPI cards, disposition ops and the caliber footnote", async () => {
    renderPage(<QualityDashboardPage />);
    // 卡片在数据到达前就渲染（显示 0）：等数字到位再断言
    await waitFor(() => expect(screen.getByTestId("kpi-total")).toHaveTextContent("35"));
    expect(screen.getByTestId("kpi-confirmed_ng")).toHaveTextContent("3");
    expect(screen.getByTestId("kpi-open")).toHaveTextContent("3");
    // 每千件处置单数、结案率与后端三指标同源显示
    expect(screen.getByTestId("disposition-ops")).toHaveTextContent("57.14");
    expect(screen.getByTestId("disposition-ops")).toHaveTextContent("40.0%");
    expect(screen.getByTestId("dashboard-footnote")).toHaveTextContent("命中率 = 已确认异常 ÷ 已关闭预警（本窗 50.0%）");
    expect(screen.queryByTestId("stale-banner")).not.toBeInTheDocument();
  });

  it("drills down with the same caliber as the card", async () => {
    renderPage(<QualityDashboardPage />);
    await screen.findByTestId("kpi-open");
    fireEvent.click(screen.getByTestId("kpi-open"));
    await waitFor(() => expect(screen.getByTestId("location-probe")).toHaveTextContent("/quality/alerts?open=1"));
    fireEvent.click(screen.getByTestId("kpi-high"));
    await waitFor(() => expect(screen.getByTestId("location-probe")).toHaveTextContent("min_severity=high"));
  });

  it("passes the four-level scope through to the aggregate read", async () => {
    renderPage(<QualityDashboardPage />);
    await waitFor(() => expect(screen.getByTestId("kpi-total")).toHaveTextContent("35"));
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "工厂" }));
    await waitFor(() => {
      const option = Array.from(document.querySelectorAll(".ant-select-item-option"))
        .find((node) => node.textContent === "F1");
      if (!option) throw new Error("option F1 not rendered");
      fireEvent.click(option);
    });
    // 选了工厂后，驾驶舱的所有读数都带着同一个范围条件重新取数（全卡联动）
    await waitFor(() => expect(mocks.apiClient.get).toHaveBeenCalledWith(
      `${MONITOR}/dashboard`, expect.objectContaining({ params: expect.objectContaining({ factory: "F1" }) }),
    ));
  });

  it("hangs the stale-data banner when production is older than a day", async () => {
    mocks.apiClient.get.mockImplementation(router({
      [`${MONITOR}/dashboard`]: { ...DASHBOARD, stale: { stale: true, last_production_at: "2026-11-24T09:00:00", hours: 49.1, never_produced: false } },
    }));
    renderPage(<QualityDashboardPage />);
    expect(await screen.findByTestId("stale-banner")).toHaveTextContent("超过 49 小时");
  });
});

describe("QualityTrendsPage（趋势与帕累托）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    localStorage.setItem("role", "owner");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation(router());
    mocks.apiClient.put.mockResolvedValue({ data: {} });
  });

  it("switches the comparison dimension and saves the NG vocabulary", async () => {
    renderPage(<QualityTrendsPage />);
    await screen.findByTestId("pareto-chart");
    fireEvent.click(screen.getByRole("radio", { name: "工位" }));
    await waitFor(() => expect(mocks.apiClient.get).toHaveBeenCalledWith(
      `${MONITOR}/trends`, expect.objectContaining({ params: expect.objectContaining({ dimension: "station", days: 7 }) }),
    ));
    const category = await screen.findByLabelText("缺陷类别 spatter");
    fireEvent.change(category, { target: { value: "飞溅（重）" } });
    fireEvent.click(screen.getByTestId("save-vocabulary"));
    await waitFor(() => expect(mocks.apiClient.put).toHaveBeenCalledWith(
      `${MONITOR}/ng-vocabulary`, { vocabulary: { spatter: "飞溅（重）" } },
    ));
    expect(screen.getByTestId("trends-footnote")).toHaveTextContent("切换对比维度只读预警表");
    expect(screen.getByTestId("print-report")).toBeInTheDocument();
  });
});

describe("QualityMonitorPage（实时生产监控）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation(router());
    mocks.apiClient.post.mockResolvedValue({ data: { acknowledged: 1, notified: 1 } });
    // jsdom 没有可读流：推送流建立失败 → 页面应降级为轮询
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("no stream")));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders the tree and station cards with device state", async () => {
    renderPage(<QualityMonitorPage />);
    expect(await screen.findByTestId("production-tree")).toHaveTextContent("甲工位（ST1）");
    expect(screen.getByTestId("card-ST1")).toHaveTextContent("设备在线");
    expect(screen.getByTestId("card-ST1")).toHaveTextContent("12（异常 2）");
    expect(screen.getByTestId("card-ST2")).toHaveTextContent("设备离线");
    expect(screen.getByTestId("ack-ST2")).toBeDisabled();
  });

  it("falls back to polling when the stream cannot be established, and pauses on demand", async () => {
    renderPage(<QualityMonitorPage />);
    await screen.findByTestId("production-tree");
    await waitFor(() => expect(screen.getByTestId("live-mode")).toHaveTextContent("轮询"));
    fireEvent.click(screen.getByRole("switch", { name: "自动刷新" }));
    await waitFor(() => expect(screen.getByTestId("live-mode")).toHaveTextContent("已暂停"));
  });

  it("acknowledges receipt and calls quality staff with a reason", async () => {
    renderPage(<QualityMonitorPage />);
    await screen.findByTestId("production-tree");
    fireEvent.click(screen.getByTestId("ack-ST1"));
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith("/projects/p1/quality-stations/st1/ack-received"));
    fireEvent.click(screen.getByTestId("call-ST1"));
    const dialog = await screen.findByRole("dialog");
    const confirm = () => within(dialog).getAllByRole("button").find((button) => /^呼\s*叫$/.test(button.textContent ?? ""));
    await waitFor(() => expect(confirm()).toBeDisabled());
    fireEvent.change(screen.getByLabelText("呼叫原因"), { target: { value: "连续三件飞溅，请到场确认" } });
    await waitFor(() => expect(confirm()).toBeEnabled());
    fireEvent.click(confirm()!);
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith(
      "/projects/p1/quality-stations/st1/call-quality", { reason: "连续三件飞溅，请到场确认" },
    ));
  });
});

describe("QualityAlertsPage drill-down parameters", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation(router());
  });

  it("applies the caliber carried in the URL so the list matches the KPI card", async () => {
    renderPage(<QualityAlertsPage />, ["/quality/alerts?open=1&min_severity=high"]);
    await waitFor(() => expect(mocks.apiClient.get).toHaveBeenCalledWith(
      "/projects/p1/quality-alerts",
      expect.objectContaining({ params: expect.objectContaining({ open: "true", min_severity: "high", page_size: 20 }) }),
    ));
  });
});
