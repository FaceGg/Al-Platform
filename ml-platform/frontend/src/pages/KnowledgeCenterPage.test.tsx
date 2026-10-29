import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import KnowledgeCenterPage from "./KnowledgeCenterPage";
import type { ExperienceEntry, KBBinding } from "../api/knowledgeCenter";

const mocks = vi.hoisted(() => ({
  listBindings: vi.fn(),
  listExperience: vi.fn(),
  patchBinding: vi.fn(),
  retireExperience: vi.fn(),
  annotateExperience: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/knowledgeCenter", () => mocks);
vi.mock("../api/client", () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: [
      { id: "kb-1", name: "拧紧工艺标准", description: "扭矩规范", document_count: 4 },
    ] }),
    post: vi.fn().mockResolvedValue({ data: { id: "kb-2" } }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      kbcenter: {
        title: "知识中心",
        refresh: "刷新",
        loadFailed: "加载失败",
        updateFailed: "更新失败",
        retireOk: "已否决",
        noteOk: "附注已保存",
        noteTitle: "附注（意见随条目存储，不改正文）",
        notePlaceholder: "人工附注",
        noteSave: "保存",
        noteCancel: "取消",
        retire: "否决",
        retireConfirm: "确认否决该经验？",
        note: "附注",
        systemTag: "系统库",
        experienceTitle: "平台经验（真源条目）",
        colName: "名称", colDocs: "文档", colEnabled: "总开关", colScope: "项目范围",
        colChat: "对话", colS1: "S1 检索", colTopK: "top_k", colTrigger: "触发",
        colSync: "经验同步", colDomain: "域", colLesson: "教训", colAction: "动作",
        colConfidence: "置信度", colStatus: "状态", colNote: "附注", colActions: "操作",
        scopeAll: "全部项目", scopeUnbound: "未绑定", syncOff: "不接收",
      },
      common: { cancel: "取消" },
    },
  }),
}));

const makeBinding = (overrides: Partial<KBBinding> = {}): KBBinding => ({
  id: "b1",
  kb_id: "kb1",
  kb_name: "点焊标准法规",
  is_system: false,
  enabled: true,
  scope_projects: ["*"],
  scope_chat: true,
  scope_agent_s1: true,
  retrieval_top_k: 5,
  retrieval_min_score: 0.15,
  retrieval_trigger: "auto",
  sync_receive_experience: true,
  sync_experience_min_confidence: 0.85,
  sync_human_review: "auto",
  doc_count: 10,
  ...overrides,
});

const makeEntry = (overrides: Partial<ExperienceEntry> = {}): ExperienceEntry => ({
  id: "e-0042",
  domain: "tightening",
  situation: "索引列被误用",
  lesson: "索引列默认剔除",
  action: "S2 drop",
  confidence: 0.86,
  origin: "distilled",
  status: "active",
  hit_count: 3,
  human_note: null,
  source_tasks: ["t1"],
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listBindings.mockResolvedValue([
    makeBinding(),
    makeBinding({ id: "b-sys", kb_name: "平台经验（系统分区）", is_system: true, doc_count: 31 }),
  ]);
  mocks.listExperience.mockResolvedValue([makeEntry()]);
});

describe("KnowledgeCenterPage", () => {
  it("renders bindings with system badge and experience entries", async () => {
    render(
      <MemoryRouter>
        <AntApp>
          <KnowledgeCenterPage />
        </AntApp>
      </MemoryRouter>
    );
    expect(await screen.findByText("平台经验（系统分区）")).toBeInTheDocument();
    expect(screen.getByText("系统库")).toBeInTheDocument();
    expect(await screen.findByText("索引列默认剔除")).toBeInTheDocument();
  });

  it("toggles a non-system binding", async () => {
    mocks.patchBinding.mockResolvedValue(makeBinding({ enabled: false }));
    render(
      <MemoryRouter>
        <AntApp>
          <KnowledgeCenterPage />
        </AntApp>
      </MemoryRouter>
    );
    await screen.findByText("点焊标准法规");
    const switches = screen.getAllByRole("switch");
    fireEvent.click(switches[0]);
    await waitFor(() =>
      expect(mocks.patchBinding).toHaveBeenCalledWith("b1", { enabled: false })
    );
  });

  it("retires an experience entry after confirmation", async () => {
    mocks.retireExperience.mockResolvedValue(undefined);
    render(
      <MemoryRouter>
        <AntApp>
          <KnowledgeCenterPage />
        </AntApp>
      </MemoryRouter>
    );
    await screen.findByText("索引列默认剔除");
    fireEvent.click(screen.getByText("否决"));
    fireEvent.click(await screen.findByRole("button", { name: /^(OK|确\s*定)$/ }));
    await waitFor(() =>
      expect(mocks.retireExperience).toHaveBeenCalledWith("e-0042")
    );
  });

  it("lists knowledge bases with document counts and manage actions", async () => {
    render(
      <MemoryRouter>
        <AntApp>
          <KnowledgeCenterPage />
        </AntApp>
      </MemoryRouter>
    );
    expect(await screen.findByText("知识库管理")).toBeInTheDocument();
    expect(await screen.findByText("拧紧工艺标准")).toBeInTheDocument();
    expect(screen.getByText("管理文档")).toBeInTheDocument();
    expect(screen.getByText("删除")).toBeInTheDocument();
  });
});
