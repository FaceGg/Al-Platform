import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import KnowledgeGraphPage from "./KnowledgeGraphPage";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get, post, delete: vi.fn() } }));
vi.mock("echarts-for-react", () => ({ default: () => <div data-testid="chart" /> }));
vi.mock("../i18n", () => ({
  useI18n: () => ({
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

const GRAPH_URL = "/knowledge/bases/kb-1/graph";
const SUMMARY_URL = `${GRAPH_URL}/extract/summary`;

const node = (id: string, name: string, type: string, method: string) => ({
  id, name, entity_type: type, properties: { source: "auto", method },
});
const edge = (id: string, source: string, target: string, type: string) => ({
  id, source, target, relation_type: type, properties: { weight: 1 },
});
const summaryOf = (overrides: Record<string, unknown> = {}) => ({
  chunks: 2,
  current: null,
  graph: { entities: 0, relations: 0 },
  rules: { extracted: false, entities: 0 },
  llm: {
    extracted: false, pending_chunks: 2, cached_chunks: 0, latest_job: null, active_job: null,
  },
  ...overrides,
});

// 画布卡片在 DOM 中先于右栏卡片
const canvasTotals = () =>
  document.querySelector('[data-testid="kg-graph-totals"]')?.textContent ?? "";

describe("KnowledgeGraphPage", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    get.mockImplementation((url: string) => {
      if (url === "/knowledge/bases") {
        return Promise.resolve({ data: [{ id: "kb-1", name: "Weld KB" }] });
      }
      if (url === GRAPH_URL) {
        return Promise.resolve({ data: { nodes: [], edges: [] } });
      }
      if (url === SUMMARY_URL) {
        return Promise.resolve({ data: summaryOf() });
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
    post.mockResolvedValue({ data: { id: "entity-1" } });
  });

  it("creates graph entities through the canonical graph route", async () => {
    render(<AntApp><KnowledgeGraphPage /></AntApp>);

    // KB 选择器在 DOM 序中最前（搜索框在其后）
    fireEvent.mouseDown((await screen.findAllByRole("combobox"))[0]);
    fireEvent.click(await screen.findByText("Weld KB"));
    fireEvent.change(await screen.findByLabelText("Entity name"), { target: { value: "Heat" } });
    fireEvent.change(screen.getByLabelText("Entity type"), { target: { value: "process" } });
    fireEvent.click(screen.getByRole("button", { name: /Add entity/ }));

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(
        "/knowledge/bases/kb-1/graph/entities",
        { name: "Heat", entity_type: "process" },
      );
    });
  });

  it("auto-extracts the graph layer from knowledge base documents", async () => {
    post.mockImplementation((url: string) => {
      if (url === `${GRAPH_URL}/extract`) {
        return Promise.resolve({ data: { entities_created: 3, relations_created: 4 } });
      }
      return Promise.resolve({ data: { id: "entity-1" } });
    });
    render(<AntApp><KnowledgeGraphPage /></AntApp>);

    // KB 选择器在 DOM 序中最前（搜索框在其后）
    fireEvent.mouseDown((await screen.findAllByRole("combobox"))[0]);
    fireEvent.click(await screen.findByText("Weld KB"));
    const extract = await screen.findByRole("button", { name: /Quick extract/ });
    fireEvent.click(extract);

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(
        "/knowledge/bases/kb-1/graph/extract",
        { mode: "rules" },
      );
    });
    // The graph is reloaded after extraction.
    await waitFor(() => {
      expect(get.mock.calls.filter(([url]) => url === GRAPH_URL).length)
        .toBeGreaterThanOrEqual(2);
    });
  });

  it("reloads the extraction summary together with the graph after a manual refresh", async () => {
    // 状态标注的数字来自摘要：手工改动后只拉图不拉摘要，标注就会停在旧数字上
    render(<AntApp><KnowledgeGraphPage /></AntApp>);

    // KB 选择器在 DOM 序中最前（搜索框在其后）
    fireEvent.mouseDown((await screen.findAllByRole("combobox"))[0]);
    fireEvent.click(await screen.findByText("Weld KB"));
    await waitFor(() => {
      expect(get.mock.calls.filter(([url]) => url === SUMMARY_URL).length).toBe(1);
    });
    // 等初始 loadGraph 落地再点刷新：慢机（CI）上摘要先于图返回，按钮仍处
    // loading 态会吞掉点击，摘要计数停在 1（run 45354020461 实证）
    await act(async () => {});

    fireEvent.click(screen.getByRole("button", { name: /Refresh/ }));
    await waitFor(() => {
      expect(get.mock.calls.filter(([url]) => url === SUMMARY_URL).length).toBe(2);
    });
  });

  it("shows the same graph scale in the canvas header and the status tag", async () => {
    // 快速抽取与深度抽取不并存：当前图谱由深度抽取生成（3 实体 / 2 关系）。
    // 画布标题栏与状态标注是同一组数字，没有第二套口径
    get.mockImplementation((url: string) => {
      if (url === "/knowledge/bases") {
        return Promise.resolve({ data: [{ id: "kb-1", name: "Weld KB" }] });
      }
      if (url === GRAPH_URL) {
        return Promise.resolve({
          data: {
            nodes: [
              node("a", "Spot welding", "process", "llm"),
              node("b", "Splash", "defect", "llm"),
              node("c", "Current", "indicator", "llm"),
            ],
            edges: [edge("e1", "a", "b", "causes"), edge("e2", "a", "c", "has_parameter")],
          },
        });
      }
      if (url === SUMMARY_URL) {
        return Promise.resolve({
          data: summaryOf({
            current: "llm",
            graph: { entities: 3, relations: 2 },
            llm: {
              extracted: true, pending_chunks: 0, cached_chunks: 2, active_job: null,
              latest_job: {
                id: "job-1", status: "succeeded", total_units: 2, done_units: 2,
                progress: 100, entities_found: 3, relations_found: 2,
              },
            },
          }),
        });
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
    render(<AntApp><KnowledgeGraphPage /></AntApp>);

    // KB 选择器在 DOM 序中最前（搜索框在其后）
    fireEvent.mouseDown((await screen.findAllByRole("combobox"))[0]);
    fireEvent.click(await screen.findByText("Weld KB"));

    expect((await screen.findByTestId("kg-deep-current")).textContent).toBe("Current graph · 3E/2R");
    await waitFor(() => expect(canvasTotals()).toBe("Entities 3 · relations 2"));
    // 深度抽取生成的图谱：快速抽取不再是「当前图谱」，也没有范围切换
    expect(screen.queryByTestId("kg-quick-current")).toBeNull();
    expect(screen.queryByText("Extraction result")).toBeNull();
  });

  it("tracks the running job's counts in the canvas header", async () => {
    // 抽取进行中：标题栏用任务行计数，与状态行进度里的数字逐项相等
    // （画布数据按节流刷新，可能落后一两片）
    const running = {
      id: "job-1", status: "running", total_units: 18, done_units: 3, progress: 16.7,
      entities_found: 25, relations_found: 24,
    };
    const nodes = Array.from({ length: 10 }, (_, i) => node(`n${i}`, `Entity ${i}`, "概念", "llm"));
    get.mockImplementation((url: string) => {
      if (url === "/knowledge/bases") {
        return Promise.resolve({ data: [{ id: "kb-1", name: "Weld KB" }] });
      }
      if (url === GRAPH_URL) {
        return Promise.resolve({
          data: {
            nodes,
            edges: Array.from({ length: 8 }, (_, i) => edge(`e${i}`, `n${i}`, `n${i + 1}`, "相关")),
          },
        });
      }
      if (url === SUMMARY_URL) {
        return Promise.resolve({
          data: summaryOf({
            current: "llm",
            graph: { entities: 10, relations: 8 },
            llm: {
              extracted: true, pending_chunks: 15, cached_chunks: 3,
              latest_job: running, active_job: running,
            },
          }),
        });
      }
      if (url === `${GRAPH_URL}/extract/jobs/job-1`) {
        return Promise.resolve({ data: running });
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
    render(<AntApp><KnowledgeGraphPage /></AntApp>);

    // KB 选择器在 DOM 序中最前（搜索框在其后）
    fireEvent.mouseDown((await screen.findAllByRole("combobox"))[0]);
    fireEvent.click(await screen.findByText("Weld KB"));

    expect(await screen.findByTestId("kg-deep-progress")).toBeTruthy();
    expect(canvasTotals()).toBe("Entities 25 · relations 24");
    expect(screen.getByText(/3\/18 · 25E\/24R/)).toBeTruthy();
  });
});
