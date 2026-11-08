import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatToolsModal from "./ChatToolsPanel";

const apiGet = vi.hoisted(() => vi.fn());
const apiPut = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({ default: { get: apiGet, put: apiPut } }));
vi.mock("../i18n", () => ({
  useI18n: () => ({ lang: "zh", t: {}, setLang: () => {} }),
}));

const TOOLS = [
  { tool: "list_datasets", label: "查看数据集列表", kind: "read", enabled: true },
  { tool: "save_insight", label: "沉淀对话洞察为经验", kind: "insight", enabled: true },
  { tool: "offline_api", label: "下线 API", kind: "write", enabled: false },
];

function renderModal() {
  return render(<ChatToolsModal open onClose={() => {}} />);
}

describe("ChatToolsModal（白名单工具全局启停配置）", () => {
  beforeEach(() => {
    localStorage.clear();
    apiGet.mockReset().mockResolvedValue({ data: { tools: TOOLS } });
    apiPut.mockReset().mockResolvedValue({ data: { disabled: ["offline_api"] } });
  });

  it("renders the global enable/disable switches directly", async () => {
    renderModal();
    expect(await screen.findByText(/查看数据集列表/)).toBeInTheDocument();
    const switches = screen.getAllByRole("switch");
    expect(switches).toHaveLength(3);
    // 初始状态与后端一致：前两个开、第三个关
    expect(switches[0]).toHaveAttribute("aria-checked", "true");
    expect(switches[2]).toHaveAttribute("aria-checked", "false");
  });

  it("saves the disabled list on confirm", async () => {
    renderModal();
    await screen.findByText(/查看数据集列表/);
    fireEvent.click(screen.getAllByRole("switch")[0]); // 关掉 list_datasets
    fireEvent.click(screen.getByRole("button", { name: /保\s*存/ }));
    await waitFor(() => expect(apiPut).toHaveBeenCalledWith("/chat-tools/config", {
      disabled: ["list_datasets", "offline_api"],
    }));
  });

  it("shows an admin-only hint when config is forbidden", async () => {
    apiGet.mockRejectedValue({ response: { status: 403 } });
    renderModal();
    expect(await screen.findByText(/仅管理员可配置白名单工具/)).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });
});
