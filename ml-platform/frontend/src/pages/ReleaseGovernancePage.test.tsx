import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
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

import ReleaseGovernancePage from "./ReleaseGovernancePage";

function renderPage(node: React.ReactElement) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <LangProvider><ThemeProvider><AntApp>{node}</AntApp></ThemeProvider></LangProvider>
    </MemoryRouter>,
  );
}

const deployment = {
  id: "dep-1",
  project_id: "p1",
  name: "点焊部署",
  model_version_id: "mv-1",
  desired_state: "active",
  observed_state: "active",
  last_error_code: null,
  last_checked_at: null,
  created_at: null,
};

/** S2b 发布治理面板（计划 §10.2 算法平台·模型运营）：空态诚实引导 +
 * 部署治理动作（challenger/影子两来源/报告/预授权/发布申请）。 */

describe("发布治理与影子面板（S2b）", () => {
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
  });

  it("无部署时诚实引导到模型库建部署", async () => {
    renderPage(<ReleaseGovernancePage />);
    expect(await screen.findByText(/暂无部署：先在模型库为目标版本创建推理部署/)).toBeInTheDocument();
  });

  it("有部署时呈现治理动作与影子两来源", async () => {
    mocks.apiClient.get.mockImplementation((url: string) => {
      if (url === "/projects") {
        return Promise.resolve({ data: { items: [{ id: "p1", name: "项目一" }] } });
      }
      if (url === "/projects/p1/inference-deployments") {
        return Promise.resolve({ data: { items: [deployment] } });
      }
      return Promise.resolve({ data: { items: [] } });
    });
    renderPage(<ReleaseGovernancePage />);
    expect(await screen.findByText(/影子候选（challenger）/)).toBeInTheDocument();
    expect(screen.getByTestId("run-shadow")).toBeInTheDocument();
    expect(screen.getByTestId("new-preauth")).toBeInTheDocument();
    expect(screen.getByTestId("new-release")).toBeInTheDocument();
    // 影子样本来源默认随机抽样，可切流量镜像（traffic_mirror 文案）
    expect(screen.getByText(/随机抽样（记种子）/)).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByText(/随机抽样（记种子）/));
    expect(await screen.findByText(/流量镜像（近期生产流量）/)).toBeInTheDocument();
    // 报告空态
    expect(screen.getByText(/暂无报告：运行一次影子打分后自动生成/)).toBeInTheDocument();
  });

  it("候选未选时影子打分按钮禁用（不发起无版本的请求）", async () => {
    mocks.apiClient.get.mockImplementation((url: string) => {
      if (url === "/projects") {
        return Promise.resolve({ data: { items: [{ id: "p1", name: "项目一" }] } });
      }
      if (url === "/projects/p1/inference-deployments") {
        return Promise.resolve({ data: { items: [deployment] } });
      }
      return Promise.resolve({ data: { items: [] } });
    });
    renderPage(<ReleaseGovernancePage />);
    const runShadow = await screen.findByTestId("run-shadow");
    expect(runShadow).toBeDisabled();
  });
});
