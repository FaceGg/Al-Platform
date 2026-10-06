import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import APIMarketplacePage from "./APIMarketplacePage";

const apiGet = vi.hoisted(() => vi.fn());
const apiPost = vi.hoisted(() => vi.fn());
const apiPut = vi.hoisted(() => vi.fn());
const apiDelete = vi.hoisted(() => vi.fn());
const apiRequest = vi.hoisted(() => vi.fn());
const formatApiError = vi.hoisted(() => vi.fn((_error, fallback) => fallback));

vi.mock("../api/client", () => ({
  default: { request: apiRequest },
  apiGet,
  apiPost,
  apiPut,
  apiDelete,
  formatApiError,
}));
vi.mock("../components/AppLayout", () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("../i18n", () => ({ useI18n: () => ({ t: { common: { success: "成功", edit: "编辑" }, api_market: { title: "API 市场", detail: "详情", test: "测试", model_api: "模型 API", custom: "自定义", copy: "复制", history: "历史", create: "新建 API" }, ai_chat: { send: "发送" } } }) }));

describe("APIMarketplacePage", () => {
  beforeEach(() => {
    apiGet.mockResolvedValue({ items: [] });
    apiPost.mockResolvedValue({});
    apiPut.mockResolvedValue({});
    apiDelete.mockResolvedValue({});
    apiRequest.mockResolvedValue({ status: 200, statusText: "OK", headers: {}, data: { ok: true } });
    vi.clearAllMocks();
    apiGet.mockResolvedValue({ items: [] });
    apiPost.mockResolvedValue({});
    apiPut.mockResolvedValue({});
    apiDelete.mockResolvedValue({});
    apiRequest.mockResolvedValue({ status: 200, statusText: "OK", headers: {}, data: { ok: true } });
  });

  it("loads APIs through the client-relative platform endpoint", async () => {
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/platform/apis"));
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/platform/apis/stats"));
    expect(screen.getByText("API 市场")).toBeInTheDocument();
  });

  it("renders live API totals from the stats endpoint", async () => {
    apiGet.mockImplementation(async (url: string) => url.endsWith("/stats")
      ? { total_apis: 7, published: 5, offline: 1, failed: 1, total_calls: 42 }
      : { items: [] });
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    expect(await screen.findByText("7")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("tests an internal endpoint through the authenticated api client", async () => {
    apiGet.mockResolvedValue({
      items: [{
        id: "api-1", name: "Primary model", api_type: "model", version: "v1",
        status: "published", method: "POST", total_calls: 0, success_calls: 0,
        endpoint: "/api/inference-deployments/deployment-1/predict", request_schema: {},
      }],
    });
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /测试/ }));
    fireEvent.click(screen.getByRole("button", { name: /发送/ }));
    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(expect.objectContaining({
      url: "/inference-deployments/deployment-1/predict",
      method: "POST",
    })));
  });

  it("creates only a custom API source", async () => {
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: /新建 API/ }));
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "Custom health" } });
    fireEvent.change(screen.getByLabelText("内部路径"), { target: { value: "/api/health" } });
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/platform/apis", expect.objectContaining({
      name: "Custom health",
      api_type: "custom",
      source_kind: "custom",
      endpoint: "/api/health",
    })));
  });

  it("edits a custom API with only mutable fields", async () => {
    apiGet.mockResolvedValue({
      items: [{
        id: "custom-1", name: "Custom one", api_type: "custom", source_kind: "custom",
        version: "v1", status: "published", method: "POST", endpoint: "/api/custom-one",
        description: "before", total_calls: 0, success_calls: 0,
      }],
    });
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /编辑/ }));
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "Custom updated" } });
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(apiPut).toHaveBeenCalledWith("/platform/apis/custom-1", {
      name: "Custom updated",
      endpoint: "/api/custom-one",
      description: "before",
    }));
  });

  it("deletes custom and orchestration APIs after confirmation", async () => {
    apiGet.mockResolvedValue({
      items: [
        { id: "custom-1", name: "Custom one", api_type: "custom", source_kind: "custom",
          version: "v1", status: "published", method: "POST", endpoint: "/api/custom-one",
          total_calls: 0, success_calls: 0 },
        { id: "orch-1", name: "Serving flow v1", api_type: "orchestration",
          source_kind: "orchestration", source_id: "wf-version-1",
          version: "v1", status: "published", method: "POST",
          endpoint: "/api/platform/apis/orchestration/wf-version-1/invoke",
          total_calls: 2, success_calls: 2 },
      ],
    });
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    // 每行都有删除动作（自定义 + 编排）。
    const deleteButtons = await screen.findAllByRole("button", { name: /删除/ });
    expect(deleteButtons.length).toBeGreaterThanOrEqual(2);
    const confirmInPopover = () => {
      // Popconfirm 渲染在 document.body 的 portal 里；关闭后 DOM 会保留（隐藏）。
      // jsdom 没有布局信息，取文档序最后一个（新开的气泡追加在最后）。
      const buttons = document.querySelectorAll<HTMLElement>(
        ".delete-confirmation__overlay .ant-btn-dangerous, .ant-popover .ant-btn-dangerous",
      );
      expect(buttons.length).toBeGreaterThan(0);
      return buttons[buttons.length - 1] as HTMLElement;
    };
    fireEvent.click(deleteButtons[0]);
    fireEvent.click(confirmInPopover());
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith("/platform/apis/custom-1"));
    fireEvent.click(deleteButtons[1]);
    fireEvent.click(confirmInPopover());
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith("/platform/apis/orch-1"));
  });

  it("renders chat APIs with a dedicated badge, filter, and delete action", async () => {
    apiGet.mockResolvedValue({
      items: [
        { id: "chat-1", name: "焊接工艺知识库 Chat", api_type: "chat", source_kind: "chat",
          source_id: "kb-1", version: "v1", status: "published", method: "POST",
          endpoint: "/api/platform/apis/chat/kb-1/invoke", total_calls: 3, success_calls: 3 },
      ],
    });
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    await screen.findByText("焊接工艺知识库 Chat");
    expect(screen.getByText("Chat")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Chat API" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Chat API" }));
    const deleteButtons = await screen.findAllByRole("button", { name: /删除/ });
    fireEvent.click(deleteButtons[0]);
    const buttons = document.querySelectorAll<HTMLElement>(
      ".delete-confirmation__overlay .ant-btn-dangerous, .ant-popover .ant-btn-dangerous",
    );
    fireEvent.click(buttons[buttons.length - 1]);
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith("/platform/apis/chat-1"));
  });

  it("hides edit/delete for deployment-bound model APIs", async () => {
    apiGet.mockResolvedValue({
      items: [{
        id: "model-1", name: "Deployment API", api_type: "model", source_kind: "model",
        source_id: "dep-1", version: "v1", status: "published", method: "POST",
        endpoint: "/api/inference-deployments/dep-1/predict", total_calls: 0, success_calls: 0,
      }],
    });
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    await screen.findByText("Deployment API");
    expect(screen.queryByRole("button", { name: /编辑/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /删除/ })).not.toBeInTheDocument();
  });

  it("shows a visible list error", async () => {
    apiGet.mockRejectedValue(new Error("offline"));
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    expect(await screen.findByText("API list loading failed")).toBeInTheDocument();
  });
});
