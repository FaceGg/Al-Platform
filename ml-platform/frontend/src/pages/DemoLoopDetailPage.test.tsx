import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DemoLoopDetailPage from "./DemoLoopDetailPage";

const demoLoopApi = vi.hoisted(() => ({
  fetchDemoLoops: vi.fn(),
  fetchDemoLoopStatusScoped: vi.fn(),
  fetchDemoLoopDeployments: vi.fn(),
  fetchDemoLoopDatasets: vi.fn(),
  fetchDemoLoopAnnotators: vi.fn(),
  predictDemoLoopRowScoped: vi.fn(),
  resetDemoLoopScoped: vi.fn(),
  updateDemoLoop: vi.fn(),
}));

vi.mock("../api/demoLoop", () => demoLoopApi);
vi.mock("../api/client", () => ({
  default: { request: vi.fn() },
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  formatApiError: vi.fn((_error: unknown, fallback: string) => fallback),
}));
vi.mock("../components/AppLayout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({ t: { nav: { demo_loop: "自动化闭环" }, demo_loop: {} } }),
}));

const CONFIG = {
  id: "cfg-1",
  project_id: "p1",
  name: "夜班告警闭环",
  deployment_id: "dep-1",
  error_classes: ["1"],
  preprocess_enabled: true,
  alert_threshold_rows: 2,
  require_review: false,
  review_annotator_ids: [],
  retrain_enabled: true,
  retrain_threshold_rows: 3,
  retrain_dataset_artifact_id: "ds-1",
  retrain_dataset_artifact_ids: ["ds-1"],
  retrain_target_column: "fault",
  retrain_max_trials: 5,
  retrain_dataset: null,
  deployment: { id: "dep-1", name: "11", desired_state: "running", observed_state: "running" },
  current_model: null,
  swapped_model_version_id: null,
  error_count: 3,
  alert_count: 1,
  total_count: 7,
  retrain_status: "completed",
  created_at: null,
  updated_at: null,
};

const STATUS = {
  config_id: "cfg-1",
  error_count: 3,
  alert_count: 1,
  total_count: 7,
  retrain_status: "completed",
  retrain_job_id: "job-9",
  review_task_id: null,
  swapped_model_version_id: null,
  error_artifact: { id: "art-1", name: "夜班告警闭环-报错数据", row_count: 3 },
  events: [],
};

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={["/demo-loop/cfg-1?project=p1"]}>
      <Routes>
        <Route path="/demo-loop/:loopId" element={<DemoLoopDetailPage />} />
        <Route path="/demo-loop" element={<div>LIST</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DemoLoopDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    demoLoopApi.fetchDemoLoops.mockResolvedValue({ items: [CONFIG] });
    demoLoopApi.fetchDemoLoopStatusScoped.mockResolvedValue(STATUS);
    demoLoopApi.fetchDemoLoopDeployments.mockResolvedValue({ items: [] });
    demoLoopApi.fetchDemoLoopDatasets.mockResolvedValue({ items: [] });
    demoLoopApi.fetchDemoLoopAnnotators.mockResolvedValue({ items: [] });
  });

  it("loads the scoped loop and renders inference + status panels", async () => {
    renderDetail();
    await waitFor(() => expect(demoLoopApi.fetchDemoLoopStatusScoped).toHaveBeenCalledWith("p1", "cfg-1"));
    expect(screen.getAllByText("夜班告警闭环").length).toBeGreaterThan(0);
    expect(screen.getByText(/逐行推理调用/)).toBeInTheDocument();
    expect(screen.getByText(/闭环状态/)).toBeInTheDocument();
    expect(screen.getByText("返回任务列表")).toBeInTheDocument();
    expect(screen.getByText(/夜班告警闭环-报错数据/)).toBeInTheDocument();
    // 已推理/回流行数来自 scoped status
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows the retrain task link from scoped status", async () => {
    renderDetail();
    await waitFor(() => expect(screen.getByText(/查看自动建模任务/)).toBeInTheDocument());
    expect(screen.getByText(/查看自动建模任务/).closest("a")).toHaveAttribute("href", "/automl/task/job-9");
  });

  it("renders back-navigation to the list page", async () => {
    renderDetail();
    await waitFor(() => expect(screen.getByText("返回任务列表")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /编辑配置/ })).toBeInTheDocument();
  });
});
