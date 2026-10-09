import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DemoLoopPage from "./DemoLoopPage";

const demoLoopApi = vi.hoisted(() => ({
  fetchDemoLoopProjects: vi.fn(),
  fetchDemoLoopConfig: vi.fn(),
  fetchDemoLoopStatus: vi.fn(),
  fetchDemoLoopDeployments: vi.fn(),
  fetchDemoLoopDatasets: vi.fn(),
  fetchDemoLoopAnnotators: vi.fn(),
  saveDemoLoopConfig: vi.fn(),
  predictDemoLoopRow: vi.fn(),
  resetDemoLoop: vi.fn(),
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
  useI18n: () => ({ t: { nav: { demo_loop: "自动化闭环" }, demo_loop: { title: "推理-回流-重训 自动化闭环" } } }),
}));

const CONFIG = {
  id: "cfg-1",
  project_id: "p1",
  name: "自动化闭环",
  deployment_id: "dep-1",
  error_classes: ["error"],
  preprocess_enabled: false,
  alert_threshold_rows: 2,
  require_review: false,
  review_annotator_ids: [],
  retrain_enabled: false,
  retrain_threshold_rows: 0,
  retrain_dataset_artifact_id: null,
  retrain_target_column: "",
  retrain_max_trials: 10,
  retrain_dataset: null,
  deployment: { id: "dep-1", name: "toy-deploy", desired_state: "running", observed_state: "running" },
  current_model: {
    model_version_id: "mv-1", version_number: 1, model_name: "toy-model",
    lifecycle_state: "enabled", approval_status: "approved", feature_schema: ["f1", "f2"],
  },
  swapped_model_version_id: null,
};

const STATUS = {
  config_id: "cfg-1",
  error_count: 3,
  alert_count: 1,
  retrain_status: "queued",
  retrain_job_id: "job-9",
  review_task_id: null,
  swapped_model_version_id: null,
  error_artifact: { id: "art-1", name: "自动化闭环-报错数据", row_count: 3 },
  events: [
    {
      id: "e1", event_type: "error_appended", severity: "warning",
      message: "错误数据已追加（当前 3 行）", payload: {}, created_at: "2026-10-01T00:00:00Z",
    },
  ],
};

describe("DemoLoopPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    demoLoopApi.fetchDemoLoopProjects.mockResolvedValue({ items: [{ id: "p1", name: "演示项目" }] });
    demoLoopApi.fetchDemoLoopConfig.mockResolvedValue(CONFIG);
    demoLoopApi.fetchDemoLoopStatus.mockResolvedValue(STATUS);
    demoLoopApi.fetchDemoLoopDeployments.mockResolvedValue({ items: [] });
    demoLoopApi.fetchDemoLoopDatasets.mockResolvedValue({ items: [] });
    demoLoopApi.fetchDemoLoopAnnotators.mockResolvedValue({ items: [] });
    demoLoopApi.saveDemoLoopConfig.mockResolvedValue(CONFIG);
    demoLoopApi.predictDemoLoopRow.mockResolvedValue({});
    demoLoopApi.resetDemoLoop.mockResolvedValue(STATUS);
  });

  it("loads project data and renders the closed-loop status", async () => {
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(demoLoopApi.fetchDemoLoopConfig).toHaveBeenCalledWith("p1"));
    await waitFor(() => expect(demoLoopApi.fetchDemoLoopStatus).toHaveBeenCalledWith("p1"));
    expect(screen.getAllByText(/自动化闭环|推理-回流-重训 自动化闭环/).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByText("3")).toBeInTheDocument());
    expect(screen.getByText("自动化闭环-报错数据")).toBeInTheDocument();
  });

  it("shows the retrain task link once a job exists", async () => {
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText(/查看自动建模任务/)).toBeInTheDocument());
    expect(screen.getByText(/查看自动建模任务/).closest("a")).toHaveAttribute("href", "/automl/task/job-9");
  });

  it("survives a missing config before first save", async () => {
    demoLoopApi.fetchDemoLoopConfig.mockRejectedValue(new Error("not found"));
    demoLoopApi.fetchDemoLoopStatus.mockRejectedValue(new Error("not found"));
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(demoLoopApi.fetchDemoLoopDeployments).toHaveBeenCalledWith("p1"));
    expect(screen.getAllByText(/闭环配置|保存配置/).length).toBeGreaterThan(0);
  });
});
