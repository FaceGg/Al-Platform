import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AIChatPage from "./AIChatPage";
const apiClient = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
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
const PROFILE = { id: "p-1", name: "DeepSeek", model_id: "deepseek-chat" };

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
      return Promise.reject(new Error("unexpected get " + url));
    });
  });

  it("shows the bound knowledge base tag and enables publish", async () => {
    renderPage();
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/knowledge/bases"));
    expect(await screen.findByText(/知识库: 焊接工艺知识库/)).toBeInTheDocument();
    const publish = screen.getByRole("button", { name: /发布为 API/ });
    expect(publish).toBeEnabled();
  });

  it("publishes the bound knowledge base as a chat API", async () => {
    apiClient.post.mockResolvedValue({ data: { id: "api-1" } });
    renderPage();
    const publish = await screen.findByRole("button", { name: /发布为 API/ });
    fireEvent.click(publish);
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/platform/apis/publish/chat/kb-1"),
    );
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

  it("keeps publish disabled without a bound knowledge base", () => {
    localStorage.removeItem("chat.kbId");
    renderPage();
    const publish = screen.getByRole("button", { name: /发布为 API/ });
    expect(publish).toBeDisabled();
  });

  it("binds a knowledge base through the settings dialog and persists the choice", async () => {
    localStorage.removeItem("chat.kbId");
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /对话设置/ }));

    // 弹窗内的知识库下拉（页面工具条也有常驻 Select，需限定 Modal 范围）
    const modalCombobox = await waitFor(() => {
      const inModal = screen.getAllByRole("combobox")
        .find((el) => el.closest(".ant-modal"));
      if (!inModal) throw new Error("modal combobox not found");
      return inModal;
    });
    fireEvent.mouseDown(modalCombobox);
    fireEvent.click(await screen.findByText("焊接工艺知识库"));
    fireEvent.click(screen.getByRole("button", { name: /保存配置/ }));

    await waitFor(() => expect(localStorage.getItem("chat.kbId")).toBe(KB.id));
    expect(await screen.findByText(/知识库: 焊接工艺知识库/)).toBeInTheDocument();
  });

  it("persists thinking level and context window choices", async () => {
    renderPage();
    // 工具条默认值落 localStorage（思考强度 off / 上下文窗口 8）
    await waitFor(() => expect(localStorage.getItem("chat.thinkingLevel")).toBe("off"));
    await waitFor(() => expect(localStorage.getItem("chat.contextWindow")).toBe("8"));
    // 输入框内嵌控件：思考强度与上下文容量条（预算 32.0K 展示存在）
    expect(await screen.findByText(/思考 关/)).toBeInTheDocument();
    await waitFor(() => {
      expect(document.body.textContent ?? "").toContain("32.0K");
    });
  });
});
