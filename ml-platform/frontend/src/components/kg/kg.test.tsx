import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Modal } from "antd";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import ExtractionActions from "./ExtractionActions";
import ExtractionStatus from "./ExtractionStatus";
import FusionPanel from "./FusionPanel";
import OntologyModal from "./OntologyModal";
import { useKgExtraction, type KgExtractSummary, type KgJobInfo } from "./useKgExtraction";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({ default: { get, post } }));
vi.mock("../../i18n", () => ({
  useI18n: () => ({ t: { common: { error: "Error", loading: "No data" } }, lang: "zh" }),
}));

const EXTRACT_URL = "/knowledge/bases/kb-1/graph/extract";
const SUMMARY_URL = `${EXTRACT_URL}/summary`;
const JOB_URL = `${EXTRACT_URL}/jobs/job-1`;

const DONE_JOB: KgJobInfo = {
  id: "job-1", status: "succeeded", total_units: 8, done_units: 8, progress: 100,
  entities_found: 24, relations_found: 22,
};

function summaryOf(overrides: {
  current?: KgExtractSummary["current"];
  graph?: { entities: number; relations: number };
  llm?: Partial<KgExtractSummary["llm"]>;
} = {}): KgExtractSummary {
  const current = overrides.current ?? null;
  return {
    chunks: 8,
    current,
    graph: overrides.graph ?? { entities: 0, relations: 0 },
    rules: {
      extracted: current === "rules",
      entities: current === "rules" ? (overrides.graph?.entities ?? 0) : 0,
    },
    llm: {
      extracted: current === "llm",
      pending_chunks: current === "llm" ? 0 : 8,
      cached_chunks: current === "llm" ? 8 : 0,
      latest_job: current === "llm" ? DONE_JOB : null,
      active_job: null,
      ...overrides.llm,
    },
  };
}

// 按路由应答：摘要 / 任务进度；其它路由报错，暴露意外的请求。
// 返回的 state.summary 可在用例中改写，模拟「抽取之后摘要变了」
function mockApi(initial: { summary: KgExtractSummary; job?: KgJobInfo }) {
  const state = { summary: initial.summary };
  get.mockImplementation((url: string) => {
    if (url === SUMMARY_URL) return Promise.resolve({ data: state.summary });
    if (url === JOB_URL) return Promise.resolve({ data: initial.job });
    return Promise.reject(new Error(`Unexpected URL: ${url}`));
  });
  return state;
}

// 与页面一致：同一个 hook 实例同时交给动作按钮和状态行
function Harness({ onExtracted }: { onExtracted: () => void }) {
  const extraction = useKgExtraction({ kbId: "kb-1", onExtracted });
  return (
    <>
      <ExtractionActions extraction={extraction} />
      <ExtractionStatus extraction={extraction} />
    </>
  );
}

describe("extraction actions and status", () => {
  let confirmMock: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    post.mockResolvedValue({ data: {} });
    confirmMock = vi
      .spyOn(Modal, "confirm")
      .mockImplementation(() => ({ destroy: vi.fn(), update: vi.fn() }) as never);
  });

  afterEach(() => {
    confirmMock.mockRestore();
  });

  // 按钮处理是异步的（点击后先确保摘要就绪）：确认框在下一个微任务才弹出
  const openedConfirm = async () => {
    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    return confirmMock.mock.calls[0][0];
  };

  it("quick extract runs directly when the KB was never extracted", async () => {
    const state = mockApi({ summary: summaryOf() });
    post.mockResolvedValue({ data: { entities_created: 3, relations_created: 2 } });
    const onExtracted = vi.fn();
    render(<Harness onExtracted={onExtracted} />);
    await screen.findAllByText("未抽取"); // 摘要已加载：当前图谱没有抽取结果
    // 抽取完成后 hook 会刷新摘要：此时服务端的摘要已变成「快速抽取生成」
    state.summary = summaryOf({ current: "rules", graph: { entities: 3, relations: 2 } });

    fireEvent.click(screen.getByRole("button", { name: /快速抽取/ }));
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(EXTRACT_URL, { mode: "rules" });
    });
    expect(confirmMock).not.toHaveBeenCalled();
    // 状态标注的数字取摘要里的图谱规模
    await waitFor(() => {
      expect(screen.getByTestId("kg-quick-current").textContent).toBe("当前图谱 · 实体 3 · 关系 2");
    });
    expect(onExtracted).toHaveBeenCalled();
  });

  it("quick extract asks before re-running on a quick-extracted KB", async () => {
    mockApi({ summary: summaryOf({ current: "rules", graph: { entities: 387, relations: 6018 } }) });
    render(<Harness onExtracted={vi.fn()} />);
    // 标注与画布标题栏是同一组数字（实体 + 关系，千分位一致）
    expect((await screen.findByTestId("kg-quick-current")).textContent).toBe("当前图谱 · 实体 387 · 关系 6,018");

    fireEvent.click(screen.getByRole("button", { name: /快速抽取/ }));
    const config = await openedConfirm();
    expect(post).not.toHaveBeenCalled(); // 确认前不执行
    expect(config.okText).toBe("重新抽取");
    expect(String(config.content)).toContain("387");

    await config.onOk?.();
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(EXTRACT_URL, { mode: "rules" });
    });
  });

  it("switching to quick extraction warns that it replaces the deep-extraction graph", async () => {
    mockApi({ summary: summaryOf({ current: "llm", graph: { entities: 24, relations: 22 } }) });
    render(<Harness onExtracted={vi.fn()} />);
    // 深度抽取生成的图谱：深度抽取标「当前图谱」，快速抽取标「未抽取」
    expect((await screen.findByTestId("kg-deep-current")).textContent).toBe("当前图谱 · 实体 24 · 关系 22");
    expect(screen.queryByTestId("kg-quick-current")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /快速抽取/ }));
    const config = await openedConfirm();
    expect(config.okText).toBe("改用快速抽取");
    expect(String(config.content)).toContain("深度抽取");
    expect(String(config.content)).toContain("替换");
    expect(post).not.toHaveBeenCalled();

    await config.onOk?.();
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(EXTRACT_URL, { mode: "rules" });
    });
  });

  it("deep extract starts directly the first time and reloads the graph when the job ends", async () => {
    mockApi({ summary: summaryOf(), job: DONE_JOB });
    post.mockResolvedValue({ data: { mode: "llm", job_id: "job-1", channel: "celery" } });
    const onExtracted = vi.fn();
    render(<Harness onExtracted={onExtracted} />);
    await screen.findAllByText("未抽取");

    fireEvent.click(screen.getByRole("button", { name: /深度抽取/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(EXTRACT_URL, { mode: "llm" }));
    expect(confirmMock).not.toHaveBeenCalled();
    // 轮询间隔 2s（真实定时器），首次轮询即终态：图谱重新拉取
    await waitFor(() => {
      expect(get).toHaveBeenCalledWith(JOB_URL);
    }, { timeout: 5000 });
    await waitFor(() => {
      expect(onExtracted).toHaveBeenCalled();
    }, { timeout: 5000 });
  }, 15000);

  it("deep extract on a deep-extracted KB with everything done asks before re-extracting all", async () => {
    mockApi({ summary: summaryOf({ current: "llm", graph: { entities: 24, relations: 22 } }) });
    render(<Harness onExtracted={vi.fn()} />);
    await screen.findByTestId("kg-deep-current");

    fireEvent.click(screen.getByRole("button", { name: /深度抽取/ }));
    const config = await openedConfirm();
    expect(post).not.toHaveBeenCalled();
    expect(config.okText).toBe("重新抽取");
    expect(String(config.content)).toContain("24");

    await config.onOk?.();
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(EXTRACT_URL, { mode: "llm", force: true });
    });
  });

  it("deep extract with unfinished chunks defaults to extracting only those", async () => {
    mockApi({
      summary: summaryOf({
        current: "llm", graph: { entities: 24, relations: 22 },
        llm: { pending_chunks: 5, cached_chunks: 3 },
      }),
    });
    render(<Harness onExtracted={vi.fn()} />);
    await screen.findByTestId("kg-deep-current");

    fireEvent.click(screen.getByRole("button", { name: /深度抽取/ }));
    const config = await openedConfirm();
    // 主按钮只补未完成的分片（省掉全部大模型调用）
    expect(config.okText).toBe("抽取未完成的 5 片");

    await config.onOk?.();
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(EXTRACT_URL, { mode: "llm" });
    });
    expect(post).not.toHaveBeenCalledWith(EXTRACT_URL, { mode: "llm", force: true });
  });

  it("the dialog offers re-extracting everything as the secondary action", async () => {
    mockApi({
      summary: summaryOf({
        current: "llm", graph: { entities: 24, relations: 22 },
        llm: { pending_chunks: 5, cached_chunks: 3 },
      }),
    });
    render(<Harness onExtracted={vi.fn()} />);
    await screen.findByTestId("kg-deep-current");

    fireEvent.click(screen.getByRole("button", { name: /深度抽取/ }));
    const config = await openedConfirm();
    const destroy = (confirmMock.mock.results[0].value as { destroy: ReturnType<typeof vi.fn> }).destroy;
    // 静态确认框被 mock 掉了：把正文渲染出来，验证次要动作确实触发全部重抽
    render(config.content as React.ReactElement);

    fireEvent.click(screen.getByRole("button", { name: "全部重新抽取" }));
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(EXTRACT_URL, { mode: "llm", force: true });
    });
    expect(destroy).toHaveBeenCalled();
  });

  it("switching to deep extraction says what gets restored and what calls the LLM", async () => {
    mockApi({
      summary: summaryOf({
        current: "rules", graph: { entities: 387, relations: 6018 },
        llm: { pending_chunks: 5, cached_chunks: 3 },
      }),
    });
    render(<Harness onExtracted={vi.fn()} />);
    await screen.findByTestId("kg-quick-current");

    fireEvent.click(screen.getByRole("button", { name: /深度抽取/ }));
    const config = await openedConfirm();
    expect(config.okText).toBe("改用深度抽取");
    render(config.content as React.ReactElement);
    expect(screen.getByText(/快速抽取与深度抽取不并存/)).toBeTruthy();
    expect(screen.getByText(/此前抽取过的 3 个分片直接恢复，其余 5 个分片调用大模型抽取/)).toBeTruthy();

    await config.onOk?.();
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(EXTRACT_URL, { mode: "llm" });
    });
    expect(post).not.toHaveBeenCalledWith(EXTRACT_URL, { mode: "llm", force: true });
  });

  it("switching back to deep extraction with everything cached needs no LLM call", async () => {
    // 当前图谱是快速抽取结果，但 8 片都深度抽过（有缓存）
    get.mockImplementation((url: string) => {
      if (url === SUMMARY_URL) {
        return Promise.resolve({
          data: summaryOf({ current: "rules", llm: { pending_chunks: 0, cached_chunks: 8 } }),
        });
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
    render(<Harness onExtracted={vi.fn()} />);
    await screen.findByTestId("kg-quick-current");

    fireEvent.click(screen.getByRole("button", { name: /深度抽取/ }));
    const config = await openedConfirm();
    render(config.content as React.ReactElement);
    expect(screen.getByText(/此前抽取过的 8 个分片将直接恢复，不再调用大模型/)).toBeTruthy();
    // 有缓存才给「全部重新抽取」：它才是要花大模型调用的那条路
    expect(screen.getByRole("button", { name: "全部重新抽取" })).toBeTruthy();

    await config.onOk?.();
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(EXTRACT_URL, { mode: "llm" });
    });
  });

  it("status line offers a resume link for an unfinished job", async () => {
    mockApi({
      summary: summaryOf({
        current: "llm", graph: { entities: 25, relations: 24 },
        llm: {
          pending_chunks: 15,
          latest_job: {
            ...DONE_JOB, status: "failed", done_units: 3, progress: 16.7,
            entities_found: 25, relations_found: 24,
            error: "interrupted before finishing (3/18 chunk attempts done)",
          },
        },
      }),
    });
    render(<Harness onExtracted={vi.fn()} />);
    // 提前结束的任务不能显示成「当前图谱」已完成的样子
    expect((await screen.findByTestId("kg-deep-incomplete")).textContent).toBe("未完成 · 已抽出实体 25");
    expect(screen.queryByTestId("kg-deep-current")).toBeNull();

    fireEvent.click(screen.getByTestId("kg-deep-resume"));
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(EXTRACT_URL, { mode: "llm" });
    });
    expect(confirmMock).not.toHaveBeenCalled(); // 「继续抽取」是明确意图，不再确认
  });

  it("a job that failed after the last chunk offers a retry that needs no LLM call", async () => {
    // 分片都抽过了、任务在收尾（归并/同步）失败：不该只剩「全部重新抽取」这一条
    // 要重花全部大模型调用的路
    mockApi({
      summary: summaryOf({
        current: "llm", graph: { entities: 109, relations: 126 },
        llm: {
          pending_chunks: 0, cached_chunks: 8,
          latest_job: {
            ...DONE_JOB, status: "failed",
            error: "ValueError: winner resolved into the loser chain; skip merge",
          },
        },
      }),
    });
    render(<Harness onExtracted={vi.fn()} />);
    expect((await screen.findByTestId("kg-deep-incomplete")).textContent).toBe("未完成 · 已抽出实体 109");
    // 状态行给「重试」：直接续建（只重做收尾），不经确认框
    expect(screen.getByTestId("kg-deep-resume").textContent).toBe("重试");

    fireEvent.click(screen.getByRole("button", { name: /深度抽取/ }));
    const config = await openedConfirm();
    expect(config.okText).toBe("重试");
    render(config.content as React.ReactElement);
    expect(screen.getByText(/不调用大模型/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "全部重新抽取" })).toBeTruthy(); // 次要动作才是全部重做

    await config.onOk?.();
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(EXTRACT_URL, { mode: "llm" });
    });
    expect(post).not.toHaveBeenCalledWith(EXTRACT_URL, { mode: "llm", force: true });
  });

  it("restores an active job on mount and keeps polling it", async () => {
    const running: KgJobInfo = {
      ...DONE_JOB, status: "running", total_units: 18, done_units: 3, progress: 16.7,
      entities_found: 25, relations_found: 24,
    };
    mockApi({
      summary: summaryOf({
        current: "rules", graph: { entities: 387, relations: 6018 },
        llm: { pending_chunks: 15, cached_chunks: 3, latest_job: running, active_job: running },
      }),
      job: running,
    });
    render(<Harness onExtracted={vi.fn()} />);

    expect(await screen.findByTestId("kg-deep-progress")).toBeTruthy();
    expect(screen.getByText(/3\/18 片 · 实体 25 · 关系 24/)).toBeTruthy();
    // 深度抽取按钮在任务进行中禁用（防重复派发）
    expect(screen.getByRole("button", { name: /深度抽取/ })).toBeDisabled();
    // 任务一启动就在替换上一轮的快速抽取结果：不再把它标成「当前图谱」
    expect(screen.queryByTestId("kg-quick-current")).toBeNull();
    await waitFor(() => {
      expect(get).toHaveBeenCalledWith(JOB_URL);
    }, { timeout: 5000 });
  }, 15000);

  it("reports a legacy KB that still holds both extraction results", async () => {
    mockApi({ summary: summaryOf({ current: "mixed", graph: { entities: 405, relations: 6018 } }) });
    render(<Harness onExtracted={vi.fn()} />);
    expect(await screen.findAllByTestId("kg-mixed")).toHaveLength(2);
    expect(screen.queryByTestId("kg-deep-current")).toBeNull();
  });

  it("loads the extraction summary on demand before deciding", async () => {
    // 摘要首次加载失败：点按钮时补拉一次，再按补拉到的状态走确认流程
    let attempts = 0;
    get.mockImplementation((url: string) => {
      if (url === SUMMARY_URL) {
        attempts += 1;
        return attempts === 1
          ? Promise.reject(new Error("boom"))
          : Promise.resolve({
              data: summaryOf({ current: "rules", graph: { entities: 387, relations: 6018 } }),
            });
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
    render(<Harness onExtracted={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /快速抽取/ }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(confirmMock.mock.calls[0][0].okText).toBe("重新抽取");
    expect(post).not.toHaveBeenCalled();
  });
});

describe("FusionPanel", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it("lists pending suggestions and accepts a merge", async () => {
    get.mockResolvedValue({
      data: [
        {
          id: "s-1", type: "merge_entity", status: "pending", method: "llm",
          similarity: 0.95, canonical_name: null,
          entity_a: { id: "a", name: "点焊", type: "工艺" },
          entity_b: { id: "b", name: "spot welding", type: "工艺" },
          payload: { reason: "同义" },
        },
      ],
    });
    post.mockResolvedValue({ data: { status: "accepted" } });
    const onChanged = vi.fn();
    render(<FusionPanel kbId="kb-1" onChanged={onChanged} />);

    await screen.findByTestId("kg-fusion-item");
    expect(screen.getByText("点焊")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /确认/ }));
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith("/knowledge/bases/kb-1/graph/fusion/suggestions/s-1/accept", {});
    });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("resolves attribute conflicts with the chosen value", async () => {
    get.mockResolvedValue({
      data: [
        {
          id: "s-2", type: "attribute_conflict", status: "pending", method: "auto",
          similarity: null, canonical_name: null,
          entity_a: { id: "a", name: "电流", type: "指标" }, entity_b: null,
          payload: { attribute: "典型值", values: [{ value: "8kA" }, { value: "10kA" }] },
        },
      ],
    });
    post.mockResolvedValue({ data: { status: "accepted" } });
    render(<FusionPanel kbId="kb-1" />);

    await screen.findByTestId("kg-conflict-radio");
    fireEvent.click(screen.getByLabelText("10kA"));
    fireEvent.click(screen.getByRole("button", { name: /确认/ }));
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(
        "/knowledge/bases/kb-1/graph/fusion/suggestions/s-2/accept",
        { resolved: { value: "10kA" } },
      );
    });
  });
});

describe("OntologyModal", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it("loads the ontology and saves edits", async () => {
    get.mockResolvedValue({
      data: {
        ontology: { entity_types: ["工艺", "缺陷"], relation_types: ["导致缺陷"] },
        custom: false,
      },
    });
    const put = vi.fn().mockResolvedValue({ data: {} });
    (await import("../../api/client")).default.put = put;
    render(<OntologyModal kbId="kb-1" open onClose={() => {}} />);

    await screen.findByText("工艺");
    expect(get).toHaveBeenCalledWith("/knowledge/bases/kb-1/graph/ontology");
    expect(screen.getByText("工艺")).toBeInTheDocument();
    expect(screen.getByText("导致缺陷")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /保\s*存/ }));
    await waitFor(() => {
      expect(put).toHaveBeenCalledWith("/knowledge/bases/kb-1/graph/ontology", {
        entity_types: ["工艺", "缺陷"],
        relation_types: ["导致缺陷"],
        kg_llm_profile_id: null,
      });
    });
  });
});
