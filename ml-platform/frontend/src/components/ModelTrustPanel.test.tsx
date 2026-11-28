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

import ModelTrustPanel from "./ModelTrustPanel";

function renderPanel(canManage = true) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <LangProvider><ThemeProvider><AntApp>
        <ModelTrustPanel projectId="p1" versionId="mv-1" versionNumber={3} canManage={canManage} />
      </AntApp></ThemeProvider></LangProvider>
    </MemoryRouter>,
  );
}

/** 模型可信度面板（B2-04，计划 §10.2 模型库——模型详情内不新增菜单）：
 * 七因子评分 + A–D 档 + CBPE（估计口径）+ 模型卡（指纹变化回 pending）+
 * 单样本解释；估计口径声明必须出现（诚实设计）。 */

describe("模型可信度面板（B2-04）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation((url: string) => {
      if (url === "/projects/p1/model-versions/mv-1/trust-score") {
        return Promise.resolve({
          data: { score: 82, grade: "A", factors: { drift: "ok", blind_f1: 0.93 }, computed_at: "2026-11-28T00:00:00" },
        });
      }
      if (url === "/projects/p1/model-versions/mv-1/trust-scores") {
        return Promise.resolve({ data: { items: [{ score: 80, grade: "B", computed_at: "2026-11-27T00:00:00" }] } });
      }
      return Promise.resolve({ data: {} });
    });
    mocks.apiClient.post.mockResolvedValue({ data: {} });
  });

  it("七因子评分 + 档位 + 历史与估计口径声明", async () => {
    renderPanel();
    expect(await screen.findByTestId("model-trust-panel")).toBeInTheDocument();
    expect(screen.getByText(/七因子可信度/)).toBeInTheDocument();
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText(/CBPE 性能估计（估计口径，非实测）/)).toBeInTheDocument();
    expect(screen.getByText(/均为估计口径（不替代盲测实测）/)).toBeInTheDocument();
    expect(screen.getByText(/版本 v3/)).toBeInTheDocument();
    expect(screen.getByTestId("refresh-card")).toBeInTheDocument();
    expect(screen.getByTestId("explain-form")).toBeInTheDocument();
  });

  it("无 model.approve 权限时模型卡重建不可用（不渲染按钮）", async () => {
    renderPanel(false);
    expect(await screen.findByTestId("model-trust-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("refresh-card")).toBeNull();
  });
});
