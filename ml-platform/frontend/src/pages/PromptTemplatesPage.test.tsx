import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PromptTemplatesPage from "./PromptTemplatesPage";
import type { PromptTemplate } from "../api/promptTemplates";

const mocks = vi.hoisted(() => ({
  listPromptTemplates: vi.fn(),
  createPromptTemplate: vi.fn(),
  deletePromptTemplate: vi.fn(),
  usePromptTemplate: vi.fn(),
  PROMPT_STAGES: ["analysis", "feature", "modeling", "evaluation"],
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/promptTemplates", () => mocks);
vi.mock("../api/client", () => ({
  default: {},
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      ptpl: {
        title: "提示词模板", refresh: "刷新", create: "新建模板",
        createOk: "模板已创建", createFailed: "创建失败", deleteOk: "已删除",
        loadFailed: "加载失败", deleteConfirm: "确认删除该模板？",
        useOk: "已复制到剪贴板", useFailed: "复制失败",
        use: "使用", del: "删除", save: "保存", cancel: "取消",
        colName: "名称", colStage: "阶段", colContent: "内容",
        colUsage: "使用次数", colActions: "操作", copyFailFallback: "请手动复制",
        namePlaceholder: "模板名称", contentPlaceholder: "提示词内容",
      },
      common: { cancel: "取消" },
    },
  }),
}));

const makeTemplate = (overrides: Partial<PromptTemplate> = {}): PromptTemplate => ({
  id: "tpl-1",
  name: "聚焦扭矩偏差",
  stage: "analysis",
  content: "重点关注扭矩-目标偏差与上下裕度",
  project_id: null,
  usage_count: 3,
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listPromptTemplates.mockResolvedValue([makeTemplate()]);
});

describe("PromptTemplatesPage", () => {
  it("renders templates with usage count", async () => {
    render(
      <AntApp>
        <PromptTemplatesPage />
      </AntApp>
    );
    expect(await screen.findByText("聚焦扭矩偏差")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("use button copies content and bumps counter", async () => {
    mocks.usePromptTemplate.mockResolvedValue(makeTemplate({ usage_count: 4 }));
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    render(
      <AntApp>
        <PromptTemplatesPage />
      </AntApp>
    );
    await screen.findByText("聚焦扭矩偏差");
    fireEvent.click(screen.getByText("使用"));
    await waitFor(() => expect(mocks.usePromptTemplate).toHaveBeenCalledWith("tpl-1"));
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("重点关注扭矩-目标偏差与上下裕度")
    );
  });

  it("deletes after confirmation", async () => {
    mocks.deletePromptTemplate.mockResolvedValue(undefined);
    render(
      <AntApp>
        <PromptTemplatesPage />
      </AntApp>
    );
    await screen.findByText("聚焦扭矩偏差");
    fireEvent.click(screen.getByText("删除"));
    fireEvent.click(await screen.findByRole("button", { name: /^(OK|确\s*定)$/ }));
    await waitFor(() => expect(mocks.deletePromptTemplate).toHaveBeenCalledWith("tpl-1"));
  });
});
