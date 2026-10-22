import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  default: {},
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      llm: {
        title: "大模型网关",
        refresh: "刷新",
        create: "新建档案",
        createTitle: "新建模型档案",
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
    expect(await screen.findByText("glm-default")).toBeInTheDocument();
    expect(screen.getByText("***abcd")).toBeInTheDocument();
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
    fireEvent.click(screen.getByText("新建档案"));
    await waitFor(() => expect(screen.getByText("新建模型档案")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "glm-backup" } });
    fireEvent.change(screen.getByLabelText("URL"), {
      target: { value: "https://api.backup.com/v1/chat/completions" },
    });
    fireEvent.change(screen.getByLabelText("model_id"), { target: { value: "glm-4.6" } });
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: fixtureKey } });
    const okButton = screen
      .getAllByRole("button")
      .find((button) => /^(OK|确\s*定)$/.test(button.textContent || ""));
    expect(okButton).toBeTruthy();
    fireEvent.click(okButton!);
    await waitFor(() => expect(mocks.createLlmProfile).toHaveBeenCalled());
    expect(mocks.createLlmProfile.mock.calls[0][0]).toMatchObject({
      name: "glm-backup",
      api_url: "https://api.backup.com/v1/chat/completions",
      model_id: "glm-4.6",
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
    fireEvent.click(screen.getByText("测试"));
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
    fireEvent.click(screen.getByText("删除"));
    await screen.findByText("确认删除该档案？");
    const confirmOk = await screen.findByRole("button", { name: /^(OK|确\s*定)$/ });
    fireEvent.click(confirmOk);
    await waitFor(() => expect(mocks.deleteLlmProfile).toHaveBeenCalledWith("profile-1"));
  });
});
