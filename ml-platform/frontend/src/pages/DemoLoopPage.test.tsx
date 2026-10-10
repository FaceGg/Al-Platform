import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DemoLoopPage from "./DemoLoopPage";

const demoLoopApi = vi.hoisted(() => ({
  fetchDemoLoopProjects: vi.fn(),
  fetchDemoLoops: vi.fn(),
  createDemoLoop: vi.fn(),
  updateDemoLoop: vi.fn(),
  deleteDemoLoop: vi.fn(),
  fetchDemoLoopStatusScoped: vi.fn(),
  predictDemoLoopRowScoped: vi.fn(),
  resetDemoLoopScoped: vi.fn(),
  fetchDemoLoopDeployments: vi.fn(),
  fetchDemoLoopDatasets: vi.fn(),
  fetchDemoLoopAnnotators: vi.fn(),
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
  error_count: 3,
  alert_count: 1,
  retrain_status: "queued",
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
    demoLoopApi.fetchDemoLoops.mockResolvedValue({ items: [CONFIG] });
    demoLoopApi.fetchDemoLoopStatusScoped.mockResolvedValue(STATUS);
    demoLoopApi.fetchDemoLoopDeployments.mockResolvedValue({ items: [] });
    demoLoopApi.fetchDemoLoopDatasets.mockResolvedValue({ items: [] });
    demoLoopApi.fetchDemoLoopAnnotators.mockResolvedValue({ items: [] });
    demoLoopApi.createDemoLoop.mockResolvedValue(CONFIG);
    demoLoopApi.updateDemoLoop.mockResolvedValue(CONFIG);
    demoLoopApi.deleteDemoLoop.mockResolvedValue({ status: "deleted" });
    demoLoopApi.predictDemoLoopRowScoped.mockResolvedValue({});
    demoLoopApi.resetDemoLoopScoped.mockResolvedValue(STATUS);
    demoLoopApi.resetDemoLoop.mockResolvedValue(STATUS);
  });

  it("loads the loop list and renders the closed-loop status", async () => {
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(demoLoopApi.fetchDemoLoops).toHaveBeenCalledWith("p1"));
    await waitFor(() => expect(demoLoopApi.fetchDemoLoopStatusScoped).toHaveBeenCalledWith("p1", "cfg-1"));
    expect(screen.getAllByText(/自动化闭环|推理-回流-重训 自动化闭环/).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByText("3")).toBeInTheDocument());
    expect(screen.getByText("自动化闭环-报错数据")).toBeInTheDocument();
  });

  it("shows the retrain task link once a job exists", async () => {
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText(/查看自动建模任务/)).toBeInTheDocument());
    expect(screen.getByText(/查看自动建模任务/).closest("a")).toHaveAttribute("href", "/automl/task/job-9");
  });

  it("creates a new loop from the task list", async () => {
    demoLoopApi.fetchDemoLoopDeployments.mockResolvedValue({
      items: [{ id: "dep-1", name: "toy-deploy", observed_state: "running" }],
    });
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("loop-task-list")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("new-loop-btn"));
    const submit = await screen.findByRole("button", { name: "创建闭环" });
    // 选择必填的推理部署
    const formItem = screen.getByText("推理部署").closest(".ant-form-item") as HTMLElement;
    fireEvent.mouseDown(formItem.querySelector(".ant-select-selector") as HTMLElement);
    const options = await screen.findAllByText(/toy-deploy/);
    const option = options.find((el) => el.closest(".ant-select-item-option")) || options[0];
    fireEvent.click(option.closest(".ant-select-item-option") ?? option);
    // 输入必填的报错类别（tags）
    const errorItem = screen.getByText(/报错类别/).closest(".ant-form-item") as HTMLElement;
    const tagInput = errorItem.querySelector("input") as HTMLInputElement;
    fireEvent.change(tagInput, { target: { value: "1" } });
    fireEvent.keyDown(tagInput, { key: "Enter", keyCode: 13, which: 13 });
    fireEvent.submit(submit.closest("form") as HTMLFormElement);
    await waitFor(() => expect(demoLoopApi.createDemoLoop).toHaveBeenCalled());
    expect(demoLoopApi.createDemoLoop.mock.calls[0][1].deployment_id).toBe("dep-1");
  });

  it("deletes a loop from the task list after confirmation", async () => {
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("loop-task-list")).toBeInTheDocument());
    const deleteButtons = screen.getAllByRole("button", { name: /delete/i });
    expect(deleteButtons.length).toBeGreaterThan(0);
    fireEvent.click(deleteButtons[0]);
    const confirmButton = await screen.findByRole("button", { name: /^(OK|确 定)$/ });
    fireEvent.click(confirmButton);
    await waitFor(() => expect(demoLoopApi.deleteDemoLoop).toHaveBeenCalledWith("p1", "cfg-1"));
  });

  it("survives an empty loop list before first create", async () => {
    demoLoopApi.fetchDemoLoops.mockResolvedValue({ items: [] });
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText(/暂无闭环任务/)).toBeInTheDocument());
    expect(screen.getAllByText(/闭环配置|新建闭环/).length).toBeGreaterThan(0);
  });
});
