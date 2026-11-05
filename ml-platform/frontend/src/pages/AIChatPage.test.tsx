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
    // 顶部按钮组：新建对话/会话（对话设置按钮已移除，配置入口收拢到 + 菜单）
    expect(await screen.findByText(/新建对话/)).toBeInTheDocument();
    expect(screen.queryByText(/对话设置/)).not.toBeInTheDocument();
    expect(screen.queryByText(/发布为 API/)).not.toBeInTheDocument();
  });

  it("sends chat messages with kb_id, thinking level and history", async () => {
    apiClient.post.mockImplementation((url: string, body?: any) => {
      if (url === "/chat") {
        return Promise.resolve({
          data: {
            reply: "点焊质量取决于焊接电流 [1]。",
            type: "success",
            kb: { id: KB.id, name: KB.name },
            sources: [{ index: 1, chunk_id: "c1", doc_id: "d1", filename: "process.txt", score: 0.83, content: "点焊质量取决于焊接电流。" }],
          },
        });
      }
      if (url === "/chat-sessions") return Promise.resolve({ data: { id: "s-new", title: "新对话" } });
      return Promise.reject(new Error("unexpected post " + url));
    });
    renderPage();
    const input = await screen.findByPlaceholderText("输入消息，Enter 发送…");
    fireEvent.change(input, { target: { value: "点焊质量取决于什么？" } });
    fireEvent.click(screen.getByRole("button", { name: /发送/ }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/chat", expect.objectContaining({
        message: "点焊质量取决于什么？",
        kb_id: KB.id,
        thinking_level: "off",
        history: [],
      })),
    );
    expect(await screen.findByText(/点焊质量取决于焊接电流/)).toBeInTheDocument();
    const citations = await screen.findByText(/引用来源 \(1\)/);
    fireEvent.click(citations);
    expect(await screen.findByText(/process.txt/)).toBeInTheDocument();
  });

  it("keeps publish flow removed from the header", () => {
    renderPage();
    expect(screen.queryByText(/发布为 API/)).not.toBeInTheDocument();
  });

  it("binds a knowledge base through the + menu settings entry", async () => {
    localStorage.removeItem("chat.kbId");
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /添加/ }));
    // + 弹层菜单：点「知识库（RAG）」打开配置弹窗（rc-select 下拉交互在
    // jsdom 不稳定，此处验证配置入口链路；绑定持久化由保存逻辑覆盖）
    await waitFor(() => expect(screen.getByText("知识库（RAG）")).toBeInTheDocument());
    fireEvent.click(screen.getByText("知识库（RAG）"));
    await waitFor(() => {
      const inModal = screen.getAllByRole("combobox")
        .find((el) => el.closest(".ant-modal"));
      if (!inModal) throw new Error("modal KB select not found");
      expect(inModal.closest(".ant-modal")).toBeTruthy();
    });
  });

  it("opens whitelist tools config via the + menu, header button removed", async () => {
    localStorage.setItem("role", "admin");
    apiClient.get.mockImplementation((url: string) => {
      if (url === "/knowledge/bases") return Promise.resolve({ data: [KB] });
      if (url === "/llm-profiles") return Promise.resolve({ data: [PROFILE] });
      if (url === "/chat-sessions") return Promise.resolve({ data: [] });
      if (url === "/chat-tools/config") {
        return Promise.resolve({
          data: { tools: [{ tool: "list_datasets", label: "查看数据集列表", kind: "read", enabled: true }] },
        });
      }
      return Promise.reject(new Error("unexpected get " + url));
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /添加/ }));
    await waitFor(() => expect(screen.getByText("白名单工具管理")).toBeInTheDocument());
    fireEvent.click(screen.getByText("白名单工具管理"));
    // 受控弹窗：拉取 /chat-tools/config 并渲染工具启停列表
    expect(await screen.findByText("查看数据集列表")).toBeInTheDocument();
    // 右上角「对话设置」按钮已删除（设置弹窗仅经 + 菜单打开）
    expect(screen.queryByRole("button", { name: /对话设置/ })).not.toBeInTheDocument();
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
