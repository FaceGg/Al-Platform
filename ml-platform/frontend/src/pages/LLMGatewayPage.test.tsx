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
    // 模型行只保留模型 ID + 配置徽标（档案名/格式/默认徽标已按要求去掉）
    expect(await screen.findByText("glm-4.6")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("***abcd")).toBeInTheDocument();
  });

  it("adds a provider from a template card and hints to fill the key", async () => {
    mocks.createLlmProfile.mockResolvedValue(makeProfile({ id: "p2", name: "DeepSeek" }));
    render(
      <AntApp>
        <LLMGatewayPage />
      </AntApp>
    );
    await screen.findByTestId("provider-detail");
    fireEvent.click(screen.getByText("添加供应商"));
    // 模板卡自动添加（无表单）：裸 base + 模板默认模型，无 Key
    const picker = screen.getByTestId("provider-picker");
    await waitFor(() => expect(within(picker).getByText("DeepSeek", { selector: "span" })).toBeInTheDocument());
    fireEvent.click(within(picker).getByText("DeepSeek", { selector: "span" }));
    await waitFor(() => expect(mocks.createLlmProfile).toHaveBeenCalled());
    expect(mocks.createLlmProfile.mock.calls[0][0]).toMatchObject({
      name: "DeepSeek",
      provider: "anthropic",
      api_url: "https://api.deepseek.com/anthropic",
      model_id: "deepseek-chat",
    });
    expect(mocks.createLlmProfile.mock.calls[0][0].api_key).toBeUndefined();
    // 自定义供应商卡：仍走表单（含 Key）
    fireEvent.click(screen.getByText("添加供应商"));
    fireEvent.click(within(screen.getByTestId("provider-picker")).getByText("创建自定义供应商")); screen.debug(undefined, 40000);
    const fixtureKey = "vitest-" + crypto.randomUUID().slice(0, 12);
    await waitFor(() => expect(screen.getByLabelText("名称")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "glm-backup" } });
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://api.backup.com/v1/chat/completions" },
    });
    // 模型字段：外层 Form.Item 只有 label，内层 AutoComplete 无 label 关联 → 按字段 id 定位
    const modelInput = document.querySelector("#model_id") as HTMLInputElement;
    fireEvent.change(modelInput, { target: { value: "glm-4.6" } });
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: fixtureKey } });
    const okButton = await screen.findByRole("button", { name: /保\s*存|Save|OK|确\s*定/ });
    fireEvent.click(okButton);
    await waitFor(() => expect(mocks.createLlmProfile).toHaveBeenCalledTimes(2));
    expect(mocks.createLlmProfile.mock.calls[1][0]).toMatchObject({
      name: "glm-backup",
      api_url: "https://api.backup.com/v1/chat/completions",
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
    await screen.findByTestId("provider-detail");
    // 模型行为图标按钮（ZCode 样式）：可访问名来自 aria-label
    fireEvent.click(screen.getByRole("button", { name: "测试" }));
    await waitFor(() => expect(mocks.testLlmProfile).toHaveBeenCalledWith("profile-1"));
  });

  it("toggles per-model enabled switch without touching is_default", async () => {
    // ZCode 样式：模型行开关绑 enabled（多模型可同时开启），不影响默认标记
    render(
      <AntApp>
        <LLMGatewayPage />
      </AntApp>
    );
    await screen.findByTestId("provider-detail");
    // 组标题与模型行都显示档案名：取右栏中带开关的模型行
    const row = within(screen.getByTestId("provider-detail")).getAllByText("glm-default")
      .map((el) => el.closest("div"))
      .find((el) => el && within(el as HTMLElement).queryAllByRole("switch").length > 0)
      ?.closest("div") as HTMLElement;
    const switches = within(row).getAllByRole("switch");
    fireEvent.click(switches[switches.length - 1]);
    await waitFor(() => expect(mocks.updateLlmProfile).toHaveBeenCalled());
    const payload = mocks.updateLlmProfile.mock.calls[0][1];
    expect(payload.enabled).toBe(false);
    expect(payload.is_default).toBe(true);
  });
});

describe("buildReasoningMapping", () => {
  it("builds a ternary chain matching the ZCode expression shape", async () => {
    const { buildReasoningMapping } = await import("./LLMGatewayPage");
    const mapping = buildReasoningMapping(["disabled", "low"]);
    expect(mapping).toContain('reasoningLevel == "disabled"');
    expect(mapping).toContain('"thinking": {');
    expect(mapping).toContain('"type": "disabled"');
    expect(mapping).toContain(': reasoningLevel == "low"');
    expect(mapping.trimEnd().endsWith(": {}")).toBe(true);
  });

  it("never uses the level name as thinking.type (upstream 422 guard)", async () => {
    // deepseek 只认 adaptive/enabled/disabled：档位名直接当 type 曾让
    // 对话整体哑掉（上游 422 → 空回复）
    const { buildReasoningMapping } = await import("./LLMGatewayPage");
    const mapping = buildReasoningMapping(["low", "high", "max"]);
    expect(mapping).not.toContain('"type": "low"');
    expect(mapping).not.toContain('"type": "high"');
    expect(mapping).not.toContain('"type": "max"');
    expect(mapping).toContain('"type": "enabled"');
  });

  it("returns empty for no levels", async () => {
    const { buildReasoningMapping } = await import("./LLMGatewayPage");
    expect(buildReasoningMapping([])).toBe("");
  });
});
