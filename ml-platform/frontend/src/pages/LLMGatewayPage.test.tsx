import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LLMGatewayPage from "./LLMGatewayPage";
import type { LLMProfile } from "../api/llmProfiles";

const mocks = vi.hoisted(() => ({
  listLlmProfiles: vi.fn(),
  createLlmProfile: vi.fn(),
  updateLlmProfile: vi.fn(),
  deleteLlmProfile: vi.fn(),
  testLlmProfile: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/llmProfiles", () => mocks);
vi.mock("../api/client", () => ({
  default: { post: vi.fn().mockResolvedValue({ data: { models: [] } }) },
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    lang: "zh",
    t: {
      llm: {
        title: "大模型管理",
        refresh: "刷新",
        create: "添加供应商",
        createTitle: "添加供应商",
        editTitle: "编辑模型档案",
        createOk: "档案已创建",
        createFailed: "创建失败",
        updateOk: "档案已更新",
        updateFailed: "更新失败",
        deleteOk: "档案已删除",
        deleteFailed: "删除失败",
        deleteConfirm: "确认删除该档案？",
    probe: "测试",
    probeOk: "连通成功",
    probeFailed: "连通失败",
    loadFailed: "加载失败",
    defaultTag: "默认",
    edit: "编辑",
    delete: "删除",
        colName: "名称",
        colProvider: "provider",
        colModel: "model_id",
        colDeployment: "部署",
        colKey: "API Key",
        colPurposes: "用途",
        colActions: "操作",
        deploymentCloud: "云端",
        deploymentPrivate: "私有",
        providerCustom: "自定义 URL",
        keyWriteOnly: "密钥只写不读，回显掩码",
        keyKeepBlank: "留空则保持不变",
        httpsOnly: "仅支持 https 地址",
        setDefault: "设为默认档案",
      },
      common: { cancel: "取消" },
    },
  }),
}));

const makeProfile = (overrides: Partial<LLMProfile> = {}): LLMProfile => ({
  id: "profile-1",
  name: "glm-default",
  provider: "openai_compatible",
  api_url: "https://api.example-llm.com/v1/chat/completions",
  model_id: "glm-4.6",
  temperature: null,
  max_tokens: null,
  timeout_seconds: 60,
  purpose_tags: ["chat", "agent"],
  deployment: "cloud",
  is_default: true,
  api_key_masked: "***abcd",
  created_at: "2026-10-22T00:00:00Z",
  updated_at: "2026-10-22T00:00:00Z",
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listLlmProfiles.mockResolvedValue([makeProfile()]);
});

describe("LLMGatewayPage", () => {
  it("renders profiles with masked key and default badge", async () => {
    render(
      <AntApp>
        <LLMGatewayPage />
      </AntApp>
    );
    await screen.findByText("glm-default").catch(() => {}); screen.debug(undefined, 30000); expect(await screen.findByText("glm-default")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("***abcd")).toBeInTheDocument();
    expect(screen.getByText("默认")).toBeInTheDocument();
  });

  it("creates a profile through the modal", async () => {
    mocks.createLlmProfile.mockResolvedValue(makeProfile({ id: "p2", name: "new" }));
    const fixtureKey = "vitest-" + crypto.randomUUID().slice(0, 12);
    render(
      <AntApp>
        <LLMGatewayPage />
      </AntApp>
    );
    await screen.findByText("glm-default");
    fireEvent.click(screen.getByText("添加供应商"));
    // 两段式：先选模板卡（预填 URL/模型），再进创建表单（在弹窗内点卡片——左栏现在也有同名供应商项）
    const picker = screen.getByTestId("provider-picker");
    await waitFor(() => expect(within(picker).getByText("DeepSeek", { selector: "span" })).toBeInTheDocument());
    fireEvent.click(within(picker).getByText("DeepSeek", { selector: "span" }));
    await waitFor(() => expect(screen.getByLabelText("名称")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "glm-backup" } });
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://api.backup.com/v1/chat/completions" },
    });
    // 模型列表为 AutoComplete：DeepSeek 模板已预填 deepseek-chat，此处不再手改
    // （受控组件原生 change 事件不生效，交互路径由「获取」按钮用例覆盖）
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: fixtureKey } });
    const okButton = await screen.findByRole("button", { name: /保\s*存|Save|OK|确\s*定/ });
    fireEvent.click(okButton);
    await waitFor(() => expect(mocks.createLlmProfile).toHaveBeenCalled());
    expect(mocks.createLlmProfile.mock.calls[0][0]).toMatchObject({
      name: "glm-backup",
      api_url: "https://api.backup.com/v1/chat/completions",
      model_id: "deepseek-chat",
      api_key: fixtureKey,
    });
  });

  it("runs a connectivity probe from the row action", async () => {
    mocks.testLlmProfile.mockResolvedValue({ ok: true, status_code: 200, latency_ms: 91.2, error: null });
    render(
      <AntApp>
        <LLMGatewayPage />
      </AntApp>
    );
    await screen.findByText("glm-default");
    const row = screen.getByText("glm-default").closest("div") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "测试" }));
    await waitFor(() => expect(mocks.testLlmProfile).toHaveBeenCalledWith("profile-1"));
  });

  it("deletes a profile after confirmation", async () => {
    mocks.deleteLlmProfile.mockResolvedValue(undefined);
    render(
      <AntApp>
        <LLMGatewayPage />
      </AntApp>
    );
    await screen.findByText("glm-default");
    // 模型行「…」菜单 → 删除 → Modal.confirm 确认
    const row = screen.getByText("glm-default").closest("div") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "更多操作" }));
    const menuItem = await screen.findByRole("menuitem", { name: /删除/ });
    fireEvent.click(menuItem);
    await screen.findByText(/将删除档案/);
    // antd 对两字中文按钮自动插空格：可访问名为「删 除」
    const confirmOk = await screen.findByRole("button", { name: /^(删\s*除|OK)$/ });
    fireEvent.click(confirmOk);
    await waitFor(() => expect(mocks.deleteLlmProfile).toHaveBeenCalledWith("profile-1"));
  });
});
