import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AIChatPage from "./AIChatPage";
const apiClient = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("../api/client", () => ({ default: apiClient }));
vi.mock("../components/AppLayout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: { ai_chat: { title: "AI 对话", not_configured: "未配置", clear: "清空", send: "发送" } },
    lang: "zh",
  }),
}));

const KB = { id: "kb-1", name: "焊接工艺知识库", document_count: 2 };
const PROFILE = { id: "p-1", name: "DeepSeek", model_id: "deepseek-chat", is_default: true };

// SSE 流响应构造：send() 已改走 /api/chat/stream2（fetch ReadableStream）
function sseResponse(events: Array<Record<string, unknown>>): Response {
  const text = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("") + "data: [DONE]\n\n";
  return new Response(text, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AIChatPage />
    </MemoryRouter>,
  );
}

describe("AIChatPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem("chat.kbId", KB.id);
    apiClient.get.mockImplementation((url: string) => {
      if (url === "/knowledge/bases") return Promise.resolve({ data: [KB] });
      if (url === "/llm-profiles") return Promise.resolve({ data: [PROFILE] });
      if (url === "/chat-sessions") return Promise.resolve({ data: [] });
      if (url === "/projects") return Promise.resolve({ data: [] });
      return Promise.reject(new Error("unexpected get " + url));
    });
    apiClient.post.mockResolvedValue({ data: {} });
    apiClient.put.mockResolvedValue({ data: {} });
    apiClient.delete.mockResolvedValue({ data: {} });
  });

  it("shows the bound knowledge base tag", async () => {
    renderPage();
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/knowledge/bases"));
    expect(await screen.findByText(/知识库: 焊接工艺知识库/)).toBeInTheDocument();
    // 顶部按钮组已精简（新建对话/会话/对话设置移至输入框左侧会话栏与 + 菜单）
    expect(screen.queryByText(/新建对话/)).not.toBeInTheDocument();
    expect(screen.queryByText(/对话设置/)).not.toBeInTheDocument();
    expect(screen.queryByText(/发布为 API/)).not.toBeInTheDocument();
    // 会话栏：新建会话按钮 + 会话列表（夹具无会话 → 空态提示）
    expect(await screen.findByText(/新建会话/)).toBeInTheDocument();
    expect(await screen.findByText(/暂无会话/)).toBeInTheDocument();
  });

  it("sends chat messages with kb_id, thinking level and history", async () => {
    apiClient.post.mockImplementation((url: string) => {
      if (url === "/chat-sessions") return Promise.resolve({ data: { id: "s-new", title: "新对话" } });
      return Promise.reject(new Error("unexpected post " + url));
    });
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([
      { type: "sources", sources: [{ index: 1, chunk_id: "c1", doc_id: "d1", filename: "process.txt", score: 0.83, content: "点焊质量取决于焊接电流。" }] },
      { type: "delta", text: "点焊质量取决于" },
      { type: "delta", text: "焊接电流 [1]。" },
      { type: "done", usage: { prompt_tokens: 40, completion_tokens: 12 } },
    ]));
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    const input = await screen.findByPlaceholderText("输入消息，Enter 发送…");
    fireEvent.change(input, { target: { value: "点焊质量取决于什么？" } });
    fireEvent.click(screen.getByRole("button", { name: /发送/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/chat/stream2");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toMatchObject({
      message: "点焊质量取决于什么？",
      kb_id: KB.id,
      thinking_level: "off",
      history: [],
    });
    // 流式增量拼接出的完整回答 + 引用折叠面板
    expect(await screen.findByText(/点焊质量取决于焊接电流/)).toBeInTheDocument();
    const citations = await screen.findByText(/引用来源 \(1\)/);
    fireEvent.click(citations);
    expect(await screen.findByText(/process\.txt/)).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("keeps publish flow removed from the header", () => {
    renderPage();
    expect(screen.queryByText(/发布为 API/)).not.toBeInTheDocument();
  });

  it("binds a knowledge base through the + menu settings entry", async () => {
    localStorage.removeItem("chat.kbId");
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /添加/ }));
    // + 弹层菜单：点「知识库」打开独立配置弹窗（rc-select 下拉交互在
    // jsdom 不稳定，此处验证配置入口链路；绑定持久化由保存逻辑覆盖）
    await waitFor(() => expect(screen.getByText("知识库")).toBeInTheDocument());
    fireEvent.click(screen.getByText("知识库"));
    await waitFor(() => {
      const inModal = screen.getAllByRole("combobox")
        .find((el) => el.closest(".ant-modal"));
      if (!inModal) throw new Error("modal KB select not found");
      expect(inModal.closest(".ant-modal")).toBeTruthy();
    });
  });

  it("persists thinking level and context window choices", async () => {
    renderPage();
    await waitFor(() => expect(localStorage.getItem("chat.thinkingLevel")).toBe("off"));
    await waitFor(() => expect(localStorage.getItem("chat.contextWindow")).toBe("8"));
    // 输入框内嵌控件：模型按钮与上下文容量圆圈
    expect(await screen.findByText(/deepseek-chat/)).toBeInTheDocument();
    expect(await screen.findByTitle(/上下文/)).toBeInTheDocument();
  });
});
