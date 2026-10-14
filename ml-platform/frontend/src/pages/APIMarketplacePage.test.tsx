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
vi.mock("../i18n", () => ({
  useI18n: () => ({
    lang: "zh",
    t: {
      common: { success: "成功", edit: "编辑" },
      ai_chat: { send: "发送" },
      api_market: {
        title: "API 市场", detail: "详情", test: "测试", custom: "自定义", copy: "复制", history: "历史",
        model_api: "模型 API", create: "新建 API",
        col_name: "API 名称", col_type: "类型", col_version: "版本", col_status: "状态", col_method: "方法",
        col_calls: "调用数", col_rate: "成功率", col_actions: "操作",
        st_published: "已发布", st_offline: "已下线", st_failed: "异常",
        type_model: "模型", type_orch: "编排", type_chat: "对话", type_custom: "自定义",
        filter_all: "全部", orch_api: "编排 API", chat_api: "对话 API",
        stat_total: "API 总数", stat_published: "已发布", stat_offline: "已下线", stat_calls: "调用总数",
        empty: "暂无 API", edit: "编辑", delete_confirm: "删除 ", detail_title: "API 详情",
        d_name: "名称", d_algorithm: "算法", d_endpoint: "端点", d_total_calls: "调用总数",
        d_success: "成功", d_failed: "失败", d_public: "公开", d_description: "描述", yes: "是", no: "否",
        test_title: "API 测试：", headers: "请求头 (Headers)", body: "请求体 (Body)",
        click_send: "点击「发送」测试该 API", copied: "已复制", field_docs: "字段解释",
        example_title: "调用示例", example_note: "远程调用示例（Bearer token 替换为你的平台令牌）",
        example_note_filled: "已填入你当前登录的令牌；复制后即可直接执行。令牌 24 小时有效，请勿外传",
        use_token: "一键填入令牌", hide_token: "隐藏令牌", token_missing: "未找到登录令牌，请先登录",
        editor_new: "新建 API", editor_edit: "编辑 API",
        f_name: "名称", f_type: "类型", f_type_value: "自定义", f_endpoint: "内部路径",
        f_endpoint_rule: "必须是 /api/ 开头的内部路径", f_method: "方法", f_version: "版本", f_description: "描述",
      },
    },
  }),
}));

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
    expect(screen.getByText("对话")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "对话 API" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "对话 API" }));
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

  it("shows response field explanations after sending (orchestration)", async () => {
    localStorage.setItem("token", "jwt-test-token");
    apiGet.mockResolvedValue({
      items: [
        { id: "orch-1", name: "方案B全闭环服务 v2", api_type: "orchestration",
          source_kind: "orchestration", source_id: "wf-version-1",
          version: "v2", status: "published", method: "POST",
          endpoint: "/api/platform/apis/orchestration/wf-version-1/invoke",
          request_schema: { record: { wld1c: 0 } },
          total_calls: 0, success_calls: 0 },
      ],
    });
    apiRequest.mockResolvedValue({
      status: 200, statusText: "OK", headers: {},
      data: { api_id: "orch-1", workflow_version: "v2", output_node: "n9",
              branch: null,
              records: [{ triggered: false, total_rows: 3, cycle_rows: 0, threshold_rows: 3 }],
              invoked_at: "2026-10-14T12:09:26Z" },
    });
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /测试/ }));
    fireEvent.click(await screen.findByRole("button", { name: /发送/ }));
    expect(await screen.findByText("字段解释")).toBeInTheDocument();
    expect(screen.getByText("records[].triggered")).toBeInTheDocument();
    expect(screen.getByText(/是否达到阈值触发自动重训/)).toBeInTheDocument();
    expect(screen.getByText(/记录命中的条件分支/)).toBeInTheDocument();
    localStorage.removeItem("token");
  });

  it("shows a visible list error", async () => {
    apiGet.mockRejectedValue(new Error("offline"));
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    expect(await screen.findByText("API list loading failed")).toBeInTheDocument();
  });

  it("prefills the model API body with real feature names, not schema metadata", async () => {
    localStorage.setItem("token", "jwt-test-token");
    apiGet.mockResolvedValue({
      items: [
        { id: "model-9", name: "自动化测试", api_type: "model", source_kind: "model",
          source_id: "dep-9", version: "v1", status: "published", method: "POST",
          endpoint: "/api/inference-deployments/dep-9/predict",
          request_schema: { records: [{ name: "wld1c", dtype: "float64" }, { name: "wld2c", dtype: "float64" }] },
          total_calls: 0, success_calls: 0 },
      ],
    });
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /测试/ }));
    const bodyBox = await screen.findAllByRole("textbox");
    const bodyText = bodyBox.map((b) => b.textContent || "").find((t) => t.includes("records"));
    expect(bodyText).toContain("wld1c");
    expect(bodyText).not.toContain("[object Object]");
    expect(bodyText).not.toContain("dtype");
    // 调用示例同样使用真实特征名
    expect(screen.getAllByText(/"wld1c": 0/).length).toBeGreaterThanOrEqual(1);
    localStorage.removeItem("token");
  });

  it("fills the login token into the call example on demand and hides it again", async () => {    localStorage.setItem("token", "jwt-test-token");
    apiGet.mockResolvedValue({
      items: [
        { id: "chat-1", name: "知识库对话", api_type: "chat", source_kind: "chat",
          source_id: "kb-1", version: "v1", status: "published", method: "POST",
          endpoint: "/api/platform/apis/chat/kb-1/invoke", total_calls: 0, success_calls: 0 },
      ],
    });
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /测试/ }));

    // 默认占位符；未登录令牌场景由浏览器 localStorage 提供
    expect(await screen.findByText(/<token>/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /一键填入令牌/ }));
    expect(screen.getByText(/Authorization: Bearer jwt-test-token/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /隐藏令牌/ }));
    expect(screen.getByText(/<token>/)).toBeInTheDocument();
    localStorage.removeItem("token");
  });

  it("warns when filling the token without a login session", async () => {
    localStorage.removeItem("token");
    apiGet.mockResolvedValue({
      items: [
        { id: "chat-1", name: "知识库对话", api_type: "chat", source_kind: "chat",
          source_id: "kb-1", version: "v1", status: "published", method: "POST",
          endpoint: "/api/platform/apis/chat/kb-1/invoke", total_calls: 0, success_calls: 0 },
      ],
    });
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /测试/ }));
    fireEvent.click(await screen.findByRole("button", { name: /一键填入令牌/ }));
    expect(await screen.findByText("未找到登录令牌，请先登录")).toBeInTheDocument();
  });
});
