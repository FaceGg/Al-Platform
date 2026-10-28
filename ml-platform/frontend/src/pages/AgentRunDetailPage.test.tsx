import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentRunDetailPage from "./AgentRunDetailPage";

const mocks = vi.hoisted(() => ({
  getAgentRun: vi.fn(),
  resumeAgentRun: vi.fn(),
}));

vi.mock("../api/agentCenter", () => mocks);
vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));

const RUN_ID = "486ea7f9-f342-49a8-a3d3-41e9ac12aff1";

// 相对当前时间生成夹具时间戳（90 分钟前的 UTC ISO），避免固定时间随真实时间流逝漂移。
const UPDATED_AT = new Date(Date.now() - 90 * 60 * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
const CREATED_AT = new Date(Date.now() - 92 * 60 * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");

const detailFixture = {
  id: RUN_ID,
  project_id: null,
  project_name: "电焊小样本",
  target_column: "fault",
  status: "waiting_escalate",
  current_stage: "s1",
  round_count: 1,
  token_used: 0,
  token_budget: null,
  llm_model_id: "deepseek-chat",
  error_code: "AGENT_S1_LLM_FAILED",
  created_at: CREATED_AT,
  updated_at: UPDATED_AT,
  dataset_artifact_id: null,
  result_json: {},
  memory_json: {
    rounds: [],
    escalation: {
      code: "AGENT_S1_LLM_FAILED",
      detail: "llm_call_failed: ReadTimeout: timed out",
      round: 1,
    },
  },
};

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/agent/task/:runId" element={<AgentRunDetailPage />} />
        <Route path="/agent" element={<div>BACK-TO-JOBS</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe("AgentRunDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getAgentRun.mockResolvedValue(detailFixture);
  });

  it("loads the archive for the routed run id and shows metadata", async () => {
    renderAt(`/agent/task/${RUN_ID}`);

    expect(mocks.getAgentRun).toHaveBeenCalledWith(RUN_ID);
    expect(await screen.findByText(/fault/)).toBeInTheDocument();
    expect(screen.getByText("电焊小样本")).toBeInTheDocument();
    expect(screen.getAllByText(/deepseek-chat/).length).toBeGreaterThan(0);
  });

  it("surfaces the persisted escalation detail (486ea7f9 diagnosability)", async () => {
    renderAt(`/agent/task/${RUN_ID}`);

    expect(await screen.findByText(/升级原因/)).toBeInTheDocument();
    expect(screen.getByText(/ReadTimeout: timed out/)).toBeInTheDocument();
  });

  it("renders relative update time in the correct timezone", async () => {
    renderAt(`/agent/task/${RUN_ID}`);
    const finalMsg = (await screen.findAllByText("终态")).find((el) => el.tagName === "B");
    const finalBlock = finalMsg?.closest(".agent-msg");
    // 90 分钟前（UTC 正确解析）必须显示为小时级相对时间；时区 bug 会显示成
    // "负偏移被钳为刚刚"或"十几小时前"级别错位——用区间断言钉住正确区间。
    expect(finalBlock?.textContent).toMatch(/[12] 小时前/);
    expect(finalBlock?.textContent).not.toMatch(/1[0-9] 小时前/);
  });

  it("shows the load failure state for a missing run", async () => {
    mocks.getAgentRun.mockRejectedValue(new Error("404"));
    renderAt(`/agent/task/${RUN_ID}`);

    expect(await screen.findByText(/档案加载失败/)).toBeInTheDocument();
  });
});
