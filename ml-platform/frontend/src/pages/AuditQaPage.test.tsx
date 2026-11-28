import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
  formatApiError: vi.fn((_e: unknown, fallback: string) => fallback),
}));

vi.mock("../api/client", () => ({
  default: mocks.apiClient,
  formatApiError: mocks.formatApiError,
}));

import AuditQaPage from "./AuditQaPage";

function renderPage(node: React.ReactElement) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <LangProvider><ThemeProvider><AntApp>{node}</AntApp></ThemeProvider></LangProvider>
    </MemoryRouter>,
  );
}

/** S4 审计问答页（计划 §10.2 智能体中心·知识与对话）：问数三态（answered/
 * clarify/denied 只走指标注册表）+ 十类模板报告 + 历史报告可重开。 */

describe("审计问答页（S4 B2-01）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation((url: string) => {
      if (url === "/projects") {
        return Promise.resolve({ data: { items: [{ id: "p1", name: "项目一" }] } });
      }
      if (url === "/projects/p1/metric-registry") {
        return Promise.resolve({
          data: { items: [{ name: "alerts_total", footnote: "口径：未关闭" }], custom_names: [] },
        });
      }
      return Promise.resolve({ data: { items: [] } });
    });
    mocks.apiClient.post.mockResolvedValue({ data: {} });
  });

  it("问数卡 + 指标注册表 + 报告空态", async () => {
    renderPage(<AuditQaPage />);
    expect(await screen.findByTestId("ask-question")).toBeInTheDocument();
    expect(await screen.findByText(/注册表指标：/)).toBeInTheDocument();
    expect(screen.getByText(/暂无报告：选择模板生成第一份/)).toBeInTheDocument();
    expect(screen.getByTestId("new-report")).toBeInTheDocument();
  });

  it("问数 answered 态展示指标值与口径脚注", async () => {
    mocks.apiClient.post.mockResolvedValue({
      data: { status: "answered", metric: "alerts_total", value: 7, footnote: "口径：未关闭" },
    });
    renderPage(<AuditQaPage />);
    const input = await screen.findByTestId("ask-question");
    fireEvent.change(input, { target: { value: "本月质量预警有多少" } });
    fireEvent.click(screen.getByTestId("ask-submit"));
    // 结构化断言（不再假设词组全局唯一——指标注册表标签同样含 alerts_total）
    const result = await screen.findByTestId("ask-result");
    expect(within(result).getByText("answered")).toBeInTheDocument();
    expect(within(result).getByText("alerts_total")).toBeInTheDocument();
    expect(within(result).getByText("7")).toBeInTheDocument();
    expect(within(result).getByText(/口径：未关闭/)).toBeInTheDocument();
  });

  it("问数 denied 态如实回显（不编造数值）", async () => {
    mocks.apiClient.post.mockResolvedValue({
      data: { status: "denied", code: "METRIC_NOT_IN_REGISTRY", message: "未命中指标注册表", known_metrics: [] },
    });
    renderPage(<AuditQaPage />);
    const input = await screen.findByTestId("ask-question");
    fireEvent.change(input, { target: { value: "今天午饭吃什么" } });
    fireEvent.click(screen.getByTestId("ask-submit"));
    expect(await screen.findByText("denied")).toBeInTheDocument();
    expect(screen.getByText(/未命中指标注册表/)).toBeInTheDocument();
  });
});
