import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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

import QualityNcrPage from "./QualityNcrPage";
import QualityD8Page from "./QualityD8Page";
import QualityCasesPage from "./QualityCasesPage";
import QualityKnowledgePage from "./QualityKnowledgePage";
import QualityTracePage from "./QualityTracePage";
import QualityReportsPage from "./QualityReportsPage";
import QualityControlPlanPage from "./QualityControlPlanPage";
import QualityMsaPage from "./QualityMsaPage";
import QualityFmeaPage from "./QualityFmeaPage";
import QualityIqcPage from "./QualityIqcPage";

function renderPage(node: React.ReactElement) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <LangProvider><ThemeProvider><AntApp>{node}</AntApp></ThemeProvider></LangProvider>
    </MemoryRouter>,
  );
}

/** 第三批质量体系十页（B3）：骨架渲染 + 空态引导（诚实设计③）。
 * 列表端点统一返回空清单，断言各页的空态文案与关键标题。 */

describe("质量体系页面骨架与空态引导（B3-04/03/07/10/09/08/06/01/02/05）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation((url: string) => {
      if (url === "/projects") {
        return Promise.resolve({ data: { items: [{ id: "p1", name: "项目一" }] } });
      }
      return Promise.resolve({ data: { items: [] } });
    });
    mocks.apiClient.post.mockResolvedValue({ data: {} });
    mocks.apiClient.delete.mockResolvedValue({ data: {} });
    mocks.apiClient.put.mockResolvedValue({ data: {} });
  });

  it("NCR-CAPA：空态引导 + 三周期门禁口径", async () => {
    renderPage(<QualityNcrPage />);
    expect(await screen.findByText("暂无 NCR：点击「登记 NCR」创建第一条，或从预警转入")).toBeInTheDocument();
    expect(screen.getByText(/连续三个验证周期/)).toBeInTheDocument();
    expect(screen.getByTestId("new-ncr")).toBeInTheDocument();
  });

  it("8D 报告：空态引导 + D6 门禁口径", async () => {
    renderPage(<QualityD8Page />);
    expect(await screen.findByText("暂无 8D 报告：点击「开立 8D」创建第一条（可关联 NCR）")).toBeInTheDocument();
    expect(screen.getByTestId("new-d8")).toBeInTheDocument();
  });

  it("案例中心：空态引导", async () => {
    renderPage(<QualityCasesPage />);
    expect(await screen.findByText("暂无案例：critical 预警关闭时自动开案，也可手工开案")).toBeInTheDocument();
  });

  it("质量知识库：空态引导 + 症状查询挂点说明", async () => {
    renderPage(<QualityKnowledgePage />);
    expect(await screen.findByText("暂无知识条目：点击「新增条目」沉淀第一条（现象 / 根因 / 措施）")).toBeInTheDocument();
    expect(screen.getByTestId("symptom-search")).toBeInTheDocument();
  });

  it("批次追溯：四对象口径说明", async () => {
    renderPage(<QualityTracePage />);
    expect(await screen.findByText(/输入样本键后追溯四对象链条/)).toBeInTheDocument();
    expect(screen.getByTestId("trace-sample")).toBeInTheDocument();
    expect(screen.getByTestId("trace-batch")).toBeInTheDocument();
  });

  it("质量报告：空态引导 + 同源口径", async () => {
    renderPage(<QualityReportsPage />);
    expect(await screen.findByText("暂无报告：定时任务每日自动补齐上一周期，也可手工补报")).toBeInTheDocument();
    expect(screen.getByText(/与趋势页同一取数路径/)).toBeInTheDocument();
  });

  it("动态控制计划：空态引导 + 双生效拒绝说明", async () => {
    renderPage(<QualityControlPlanPage />);
    expect(await screen.findByText("暂无控制计划：点击「新版计划」创建第一版（生效后同项目唯一）")).toBeInTheDocument();
    expect(screen.getByText(/仅一份生效计划/)).toBeInTheDocument();
  });

  it("MSA：空态引导 + AIAG 口径标注", async () => {
    renderPage(<QualityMsaPage />);
    expect(await screen.findByText("暂无 MSA 研究：点击「新研究」录入读数矩阵")).toBeInTheDocument();
    expect(screen.getByText(/待质量专家评审|AIAG/)).toBeInTheDocument();
  });

  it("FMEA：空态引导 + 服务端 RPN 口径", async () => {
    renderPage(<QualityFmeaPage />);
    expect(await screen.findByText("暂无 FMEA：点击「新 FMEA」登记失效模式")).toBeInTheDocument();
    expect(screen.getByText(/服务端计算/)).toBeInTheDocument();
  });

  it("来料检验与 SCAR：三张台账空态", async () => {
    renderPage(<QualityIqcPage />);
    expect(await screen.findByText("暂无供应商：点击「供应商」登记第一家")).toBeInTheDocument();
    expect(screen.getByText("暂无检验记录：点击「来料检验」登记（不良自动生成 SCAR）")).toBeInTheDocument();
    expect(screen.getByText("暂无 SCAR：检验不合格自动生成")).toBeInTheDocument();
  });
});
