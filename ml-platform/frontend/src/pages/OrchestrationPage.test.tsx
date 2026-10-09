import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OrchestrationPage from "./OrchestrationPage";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  apiGet: vi.fn(),
  formatApiError: vi.fn((_error: unknown, fallback: string) => fallback),
}));
vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useLocation: () => ({ pathname: "/orchestration", search: "", hash: "", state: null, key: "test" }),
}));
vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({
  default: api,
  apiGet: api.apiGet,
  apiPost: api.post,
  apiDelete: api.delete,
  formatApiError: api.formatApiError,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    lang: "zh",
    t: {
      common: { delete: "删除", success: "成功" },
      orchestration: {
        title: "应用编排 · 服务图", project: "项目", name: "名称", description: "描述",
        new_workflow: "新建服务图", publish_api: "发布为 API", edit: "编辑图",
        updated: "更新时间", actions: "操作", refresh: "刷新",
        created: "服务图已创建", deleted: "已删除",
      },
    },
  }),
}));

describe("OrchestrationPage (serving-graph workbench)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // 页面 /projects 与 workflows 都走 apiGet。
    api.apiGet.mockImplementation((url: string) => {
      if (url === "/projects") {
        return Promise.resolve({ items: [{ id: "p1", name: "点焊" }] });
      }
      if (url === "/projects/p1/workflows") {
        return Promise.resolve({ items: [
          { id: "wf-1", name: "推理服务", description: "焊接质量", updated_at: "2026-10-01T10:00:00" },
        ] });
      }
      return Promise.resolve({ items: [] });
    });
    api.post.mockResolvedValue({ data: {} });
    api.delete.mockResolvedValue({});
  });

  it("lists the project workflows as serving graphs with publish and edit actions", async () => {
    const { container } = render(<OrchestrationPage />);
    await waitFor(() => expect(api.apiGet).toHaveBeenCalledWith("/projects/p1/workflows"));
    await waitFor(() => {
      expect(container.textContent).toContain("推理服务");
    }, { timeout: 3000 });
    expect(screen.getByRole("button", { name: /发布为 API/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /编辑图/ })).toBeInTheDocument();
  });

  it("creates a workflow with empty graph payload", async () => {
    api.post.mockResolvedValue({ data: { id: "wf-new" } });
    render(<OrchestrationPage />);
    fireEvent.click(await screen.findByRole("button", { name: /新建服务图/ }));
    await screen.findByRole("dialog");
    // antd Modal onOk 的合成点击在 jsdom 下不稳定；直接派发 form submit 触发 onFinish
    const dialog = screen.getByRole("dialog");
    const input = dialog.querySelector("input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "焊接质量推理服务" } });
    const form = dialog.querySelector("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form as HTMLFormElement);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/projects/p1/workflows", {
      name: "焊接质量推理服务",
      description: "",
      nodes: [],
      edges: [],
    }));
  });

  it("renders an enabled publish action per workflow row", async () => {
    render(<OrchestrationPage />);
    await screen.findByText("推理服务");
    // antd Table 行按钮在 jsdom 下的合成点击不可靠（React 18 委派 + loading 锁），
    // 发布流程的端到端验证在 Playwright 浏览器测试中完成；这里验证按钮存在且可用。
    const publishButtons = screen.getAllByRole("button", { name: /发布为 API/ });
    expect(publishButtons.length).toBeGreaterThanOrEqual(1);
    for (const button of publishButtons) {
      expect((button as HTMLButtonElement).disabled).toBe(false);
    }
  });

  it("opens the delete confirmation popover per workflow row", async () => {
    render(<OrchestrationPage />);
    fireEvent.click(await screen.findByRole("button", { name: /删除/ }));
    // Popconfirm 渲染在 body portal；确认点击在 jsdom + antd Popconfirm 下不稳定，
    // 完整删除流程在 Playwright 浏览器测试中验证，这里验证气泡弹出且含确认按钮。
    await waitFor(() => {
      const el = document.querySelector(".ant-popover.ant-popconfirm");
      expect(el).not.toBeNull();
    }, { timeout: 3000 });
    const popover = document.querySelector(".ant-popover.ant-popconfirm") as HTMLElement;
    expect(/删\s*除/.test(popover.textContent || "")).toBe(true);
  });

  it("shows the empty state when the project has no workflows", async () => {
    api.apiGet.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ items: [{ id: "p1", name: "点焊" }] });
      return Promise.resolve({ items: [] });
    });
    const { container } = render(<OrchestrationPage />);
    await waitFor(() => expect(api.apiGet).toHaveBeenCalledWith("/projects/p1/workflows"));
    await waitFor(() => {
      expect(container.textContent).toContain("还没有服务图");
    }, { timeout: 3000 });
  });
});
