import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import KnowledgeGraphPage from "./KnowledgeGraphPage";

// jsdom 无 canvas 实现；图谱绘制在测试中打桩跳过。
beforeAll(() => {
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    return 0;
  });
  (HTMLCanvasElement.prototype as any).getContext = vi.fn(() => null);
});

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get, post, delete: vi.fn() } }));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    lang: "zh",
    t: {
      common: { error: "Error", success: "Success", loading: "No data" },
      nav: { data: "Data" },
      monitor: { refresh: "Refresh" },
      knowledge: {
        graph: "Knowledge Graph", title: "Knowledge Base", add_entity: "Add entity",
        entity_name: "Entity name", entity_type: "Entity type", relation: "Relation",
        relation_type: "Relation type", entity: "Entity",
      },
    },
  }),
}));

describe("KnowledgeGraphPage", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    get.mockImplementation((url: string) => {
      if (url === "/knowledge/bases") {
        return Promise.resolve({ data: [{ id: "kb-1", name: "Weld KB" }] });
      }
      if (url === "/knowledge/bases/kb-1/graph") {
        return Promise.resolve({ data: { nodes: [], edges: [] } });
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
    post.mockResolvedValue({ data: { id: "entity-1" } });
  });

  it("renders the display-only graph view: entity list left, canvas right, no edit forms", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/knowledge/bases") {
        return Promise.resolve({ data: [{ id: "kb-1", name: "Weld KB" }] });
      }
      if (url === "/knowledge/bases/kb-1/graph") {
        return Promise.resolve({ data: {
          nodes: [
            { id: "n1", name: "点焊工艺", entity_type: "process", properties: { source: "auto" } },
            { id: "n2", name: "GB 9448", entity_type: "standard", properties: { source: "auto" } },
          ],
          edges: [{ source_id: "n1", target_id: "n2", relation_type: "applies_to" }],
        } });
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
    render(<AntApp><KnowledgeGraphPage /></AntApp>);

    fireEvent.mouseDown((await screen.findAllByRole("combobox"))[0]);
    fireEvent.click(await screen.findByText("Weld KB"));
    expect(await screen.findByText("实体列表")).toBeInTheDocument();
    expect(await screen.findByText("点焊工艺")).toBeInTheDocument();
    // 纯展示：无添加实体/关系表单与删除按钮
    expect(screen.queryByText("Entity name")).not.toBeInTheDocument();
    expect(screen.queryByText(/Add entity/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete/ })).not.toBeInTheDocument();
    // 自动抽取（数据生成）保留在工具栏
    expect(screen.getByRole("button", { name: /自动抽取/ })).toBeInTheDocument();
  });

  it("auto-extracts the graph layer from knowledge base documents", async () => {
    post.mockImplementation((url: string) => {
      if (url === "/knowledge/bases/kb-1/graph/extract") {
        return Promise.resolve({ data: { entities_created: 3, relations_created: 4 } });
      }
      return Promise.resolve({ data: { id: "entity-1" } });
    });
    render(<AntApp><KnowledgeGraphPage /></AntApp>);

    // KB 选择器在 DOM 序中最前（搜索框在其后）
    fireEvent.mouseDown((await screen.findAllByRole("combobox"))[0]);
    fireEvent.click(await screen.findByText("Weld KB"));
    const extract = await screen.findByRole("button", { name: /自动抽取/ });
    fireEvent.click(extract);

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith("/knowledge/bases/kb-1/graph/extract");
    });
    // The graph is reloaded after extraction.
    await waitFor(() => {
      expect(get.mock.calls.filter(([url]) => url === "/knowledge/bases/kb-1/graph").length)
        .toBeGreaterThanOrEqual(2);
    });
  });
});
