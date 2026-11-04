import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatToolsPanel from "./ChatToolsPanel";

const apiGet = vi.hoisted(() => vi.fn());
const apiPost = vi.hoisted(() => vi.fn());
const onResult = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({ default: { get: apiGet, post: apiPost } }));
vi.mock("../i18n", () => ({
  useI18n: () => ({ lang: "zh", t: {}, setLang: () => {} }),
}));

describe("ChatToolsPanel (whitelist tools + write confirmation)", () => {
  beforeEach(() => {
    localStorage.clear();
    apiGet.mockReset().mockResolvedValue({ data: {
      read_tools: [{ tool: "list_projects", label: "查看项目列表", kind: "read", enabled: true }],
      insight_tools: [{ tool: "save_insight", label: "沉淀对话洞察为经验", kind: "insight", enabled: true }],
      write_tools: [{ tool: "retrain_swap", label: "闭环重训换模", kind: "write", enabled: true }],
    } });
    apiPost.mockReset();
    onResult.mockClear();
  });

  it("renders whitelist chips grouped by kind", async () => {
    render(<ChatToolsPanel onResult={onResult} />);

    fireEvent.click(await screen.findByRole("button", { name: /白名单工具/ }));
    expect(await screen.findByText(/查看项目列表/)).toBeInTheDocument();
    expect(screen.getByText(/沉淀对话洞察为经验/)).toBeInTheDocument();
    expect(screen.getByText(/闭环重训换模/)).toBeInTheDocument();
  });

  it("runs read tools directly and streams the result", async () => {
    apiPost.mockResolvedValue({ data: { status: "success", result: { projects: 2 } } });
    render(<ChatToolsPanel onResult={onResult} />);

    fireEvent.click(await screen.findByRole("button", { name: /白名单工具/ }));
    fireEvent.click(await screen.findByText(/查看项目列表/));
    fireEvent.click(await screen.findByRole("button", { name: "执行" }));

    await waitFor(() => expect(onResult).toHaveBeenCalledWith(expect.stringContaining('"projects": 2')));
    expect(apiPost).toHaveBeenCalledWith("/chat-tools/execute", {
      tool: "list_projects", params: {}, confirmed: false,
    });
  });

  it("gates write tools behind an explicit confirmation step", async () => {
    apiPost.mockImplementation((_url: string, payload: any) =>
      payload.confirmed
        ? Promise.resolve({ data: { status: "success", result: { swapped: true } } })
        : Promise.resolve({ data: { status: "confirmation_required", code: "CHAT_TOOL_CONFIRMATION_REQUIRED", tool: "retrain_swap", message: "写操作需要用户在对话中确认后执行" } }));
    render(<ChatToolsPanel onResult={onResult} />);

    fireEvent.click(await screen.findByRole("button", { name: /白名单工具/ }));
    fireEvent.click(await screen.findByText(/闭环重训换模/));
    fireEvent.click(await screen.findByRole("button", { name: "执行" }));

    // First attempt comes back as confirmation_required; the confirm card appears.
    expect(await screen.findByText(/写操作需要用户在对话中确认后执行/)).toBeInTheDocument();
    expect(onResult).not.toHaveBeenCalled();
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(apiPost.mock.calls[0][1]).toEqual({ tool: "retrain_swap", params: {}, confirmed: false });

    // Only the explicit confirm re-submits with confirmed=true.
    fireEvent.click(await screen.findByRole("button", { name: "确认执行" }));
    await waitFor(() => expect(onResult).toHaveBeenCalled());
    expect(apiPost).toHaveBeenCalledTimes(2);
    expect(apiPost.mock.calls[1][1]).toEqual({ tool: "retrain_swap", params: {}, confirmed: true });
  });

  it("rejects invalid JSON params without calling the API", async () => {
    render(<ChatToolsPanel onResult={onResult} />);
    fireEvent.click(await screen.findByRole("button", { name: /白名单工具/ }));
    fireEvent.click(await screen.findByText(/查看项目列表/));
    fireEvent.change(await screen.findByLabelText("工具参数 JSON"), { target: { value: "{bad" } });
    fireEvent.click(screen.getByRole("button", { name: "执行" }));

    expect(await screen.findByText(/参数不是合法 JSON/)).toBeInTheDocument();
    expect(apiPost).not.toHaveBeenCalled();
  });
});
