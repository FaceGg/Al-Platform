import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatToolsConfigModal from "./ChatToolsConfigModal";

const apiGet = vi.hoisted(() => vi.fn());
const apiPost = vi.hoisted(() => vi.fn());
const apiPut = vi.hoisted(() => vi.fn());
const onResult = vi.hoisted(() => vi.fn());
const onClose = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({ default: { get: apiGet, post: apiPost, put: apiPut } }));
vi.mock("../i18n", () => ({
  useI18n: () => ({ lang: "zh", t: {}, setLang: () => {} }),
}));

const CONFIG_TOOLS = {
  tools: [
    { tool: "list_projects", label: "查看项目列表", kind: "read", enabled: true },
    { tool: "save_insight", label: "沉淀对话洞察为经验", kind: "insight", enabled: true },
    { tool: "retrain_swap", label: "闭环重训换模", kind: "write", enabled: false },
  ],
};

const WHITELIST = {
  read_tools: [{ tool: "list_projects", label: "查看项目列表", kind: "read", enabled: true }],
  insight_tools: [{ tool: "save_insight", label: "沉淀对话洞察为经验", kind: "insight", enabled: true }],
  write_tools: [{ tool: "retrain_swap", label: "闭环重训换模", kind: "write", enabled: true }],
};

/** 工具行按钮与参数面板执行按钮同名：按行文本定位所在行，再返回面板容器收窄。 */
async function openParamPanel(rowLabel: RegExp) {
  await screen.findAllByText(rowLabel); // 等列表加载
  const row = screen.getAllByText(rowLabel).map((t) => t.closest("div")).find(Boolean);
  if (!row) throw new Error("tool row not found");
  fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "执行" }));
  return within((await screen.findByLabelText("工具参数 JSON")).closest("div") as HTMLElement);
}

describe("ChatToolsConfigModal (+ 菜单白名单工具弹窗)", () => {
  beforeEach(() => {
    localStorage.clear();
    apiGet.mockReset().mockResolvedValue({ data: CONFIG_TOOLS });
    apiPost.mockReset();
    apiPut.mockReset().mockResolvedValue({ data: {} });
    onResult.mockClear();
    onClose.mockClear();
  });

  it("admin: loads config, toggles switches and saves the disabled list", async () => {
    localStorage.setItem("role", "admin");
    render(<ChatToolsConfigModal open onClose={onClose} onResult={onResult} />);

    expect(await screen.findByText(/查看项目列表/)).toBeInTheDocument();
    const switches = screen.getAllByRole("switch");
    expect(switches).toHaveLength(3);

    // 切换启用→停用 list_projects；保存后 PUT disabled=切换项+配置内原有停用项
    fireEvent.click(switches[0]);
    fireEvent.click(screen.getByRole("button", { name: /保\s*存/ }));
    await waitFor(() =>
      expect(apiPut).toHaveBeenCalledWith("/chat-tools/config", {
        disabled: ["list_projects", "retrain_swap"],
      }),
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("non-admin: read-only whitelist (no switches) and runs a read tool", async () => {
    apiGet.mockResolvedValue({ data: WHITELIST });
    apiPost.mockResolvedValue({ data: { status: "success", result: { projects: 2 } } });
    render(<ChatToolsConfigModal open onClose={onClose} onResult={onResult} />);

    expect(await screen.findByText(/查看项目列表/)).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();

    const panel = await openParamPanel(/查看项目列表/);
    fireEvent.click(panel.getByRole("button", { name: "执行" }));
    await waitFor(() =>
      expect(onResult).toHaveBeenCalledWith(expect.stringContaining('"projects": 2')),
    );
    expect(apiPost).toHaveBeenCalledWith("/chat-tools/execute", {
      tool: "list_projects", params: {}, confirmed: false,
    });
  });

  it("gates write tools behind an explicit confirmation step", async () => {
    apiGet.mockResolvedValue({ data: WHITELIST });
    apiPost.mockImplementation((_url: string, payload: any) =>
      payload.confirmed
        ? Promise.resolve({ data: { status: "success", result: { swapped: true } } })
        : Promise.resolve({ data: { status: "confirmation_required", code: "CHAT_TOOL_CONFIRMATION_REQUIRED", tool: "retrain_swap", message: "写操作需要用户在对话中确认后执行" } }));
    render(<ChatToolsConfigModal open onClose={onClose} onResult={onResult} />);

    const panel = await openParamPanel(/闭环重训换模/);
    fireEvent.click(panel.getByRole("button", { name: "执行" }));

    // 首次未确认 → confirmation_required 确认卡
    expect(await screen.findByText(/写操作需要用户在对话中确认后执行/)).toBeInTheDocument();
    expect(onResult).not.toHaveBeenCalled();
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(apiPost.mock.calls[0][1]).toEqual({ tool: "retrain_swap", params: {}, confirmed: false });

    // 只有显式确认才以 confirmed=true 重发
    fireEvent.click(await screen.findByRole("button", { name: "确认执行" }));
    await waitFor(() => expect(onResult).toHaveBeenCalled());
    expect(apiPost).toHaveBeenCalledTimes(2);
    expect(apiPost.mock.calls[1][1]).toEqual({ tool: "retrain_swap", params: {}, confirmed: true });
  });

  it("rejects invalid JSON params without calling the API", async () => {
    apiGet.mockResolvedValue({ data: WHITELIST });
    render(<ChatToolsConfigModal open onClose={onClose} onResult={onResult} />);

    const panel = await openParamPanel(/查看项目列表/);
    fireEvent.change(await screen.findByLabelText("工具参数 JSON"), { target: { value: "{bad" } });
    fireEvent.click(panel.getByRole("button", { name: "执行" }));

    expect(await screen.findByText(/参数不是合法 JSON/)).toBeInTheDocument();
    expect(apiPost).not.toHaveBeenCalled();
  });
});
