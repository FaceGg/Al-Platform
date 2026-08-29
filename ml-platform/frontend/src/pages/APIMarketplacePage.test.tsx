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

  it("shows a visible list error", async () => {
    apiGet.mockRejectedValue(new Error("offline"));
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    expect(await screen.findByText("API list loading failed")).toBeInTheDocument();
  });
});
