import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AIChatPage from "./AIChatPage";const apiClient = vi.hoisted(() => ({
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
      if (url === "/chat/status") return Promise.resolve({ data: { configured: false, model: "not set" } });
      if (url === "/knowledge/bases") return Promise.resolve({ data: [KB] });
      return Promise.reject(new Error("unexpected get " + url));
    });
  });

  it("shows the bound knowledge base tag and enables publish", async () => {
    renderPage();
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/chat/status"));
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

  it("sends chat messages with the bound kb_id and renders citations", async () => {
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
    const input = await screen.findByPlaceholderText("输入有关焊接制造的问题...");
    fireEvent.change(input, { target: { value: "点焊质量取决于什么？" } });
    fireEvent.click(screen.getByRole("button", { name: /发送/ }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/chat", expect.objectContaining({
        message: "点焊质量取决于什么？",
        kb_id: KB.id,
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
    fireEvent.click(await screen.findByRole("button", { name: /对话配置/ }));

    const combobox = await screen.findByRole("combobox");
    fireEvent.mouseDown(combobox);
    fireEvent.click(await screen.findByText("焊接工艺知识库"));
    fireEvent.click(screen.getByRole("button", { name: /保存配置/ }));

    await waitFor(() => expect(localStorage.getItem("chat.kbId")).toBe(KB.id));
    expect(await screen.findByText(/知识库: 焊接工艺知识库/)).toBeInTheDocument();
  });
});
