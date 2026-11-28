import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LangProvider } from "../../i18n";
import { ThemeProvider } from "../../stores/themeContext";
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

vi.mock("../../api/client", () => ({
  default: mocks.apiClient,
  formatApiError: mocks.formatApiError,
}));

import LabelQualityPanel from "./LabelQualityPanel";

function renderPanel() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <LangProvider><ThemeProvider><AntApp><LabelQualityPanel projectId="p1" /></AntApp></ThemeProvider></LangProvider>
    </MemoryRouter>,
  );
}

/** S3 标注质量面板（计划 §10.2 标注页内页签）：一致性轮/仲裁/主动学习/
 * 伪标签四组操作 + E15 质量门状态卡；盲标无 subject 输入（绑定登录用户）。 */

describe("标注质量面板（S3 B2-05/06/G4）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation((url: string) => {
      if (url === "/projects/p1/label-quality/gate") {
        return Promise.resolve({ data: { status: "not_available", kappa: null, threshold: 0.6 } });
      }
      return Promise.resolve({ data: { items: [] } });
    });
    mocks.apiClient.post.mockResolvedValue({ data: {} });
    mocks.apiClient.put.mockResolvedValue({ data: {} });
  });

  it("四组操作入口与 E15 质量门状态卡", async () => {
    renderPanel();
    expect(await screen.findByTestId("label-quality-panel")).toBeInTheDocument();
    expect(screen.getByText(/E15 标签质量门/)).toBeInTheDocument();
    expect(screen.getByText(/一致性轮（Kappa 仲裁 B2-06）/)).toBeInTheDocument();
    expect(screen.getByText(/仲裁队列/)).toBeInTheDocument();
    expect(screen.getByText(/主动学习选样（B2-05）/)).toBeInTheDocument();
    expect(screen.getByText(/伪标签批（B2-G4）/)).toBeInTheDocument();
  });

  it("盲标表单无 subject 输入（身份绑登录用户，第三轮复审 #28）", async () => {
    renderPanel();
    // 展开「标注质量」面板组（盲标表单在折叠面板内）
    fireEvent.click(await screen.findByText(/一致性轮（Kappa 仲裁 B2-06）/));
    expect(screen.getByTestId("blind-form")).toBeInTheDocument();
    expect(screen.queryByLabelText(/标注员身份/)).toBeNull();
  });

  it("一致性轮表单要求 ≥2 标注员与样本列表", async () => {
    mocks.apiClient.get.mockImplementation((url: string) => {
      if (url === "/projects/p1/label-quality/gate") {
        return Promise.resolve({ data: { status: "not_available" } });
      }
      if (url === "/annotators") {
        return Promise.resolve({
          data: { items: [{ id: "u1", username: "annot-a" }, { id: "u2", username: "annot-b" }] },
        });
      }
      return Promise.resolve({ data: { items: [] } });
    });
    renderPanel();
    // 展开一致性轮面板
    fireEvent.click(await screen.findByText(/一致性轮（Kappa 仲裁 B2-06）/));
    expect(screen.getByTestId("round-form")).toBeInTheDocument();
    expect(screen.getByTestId("kappa-form")).toBeInTheDocument();
  });
});
