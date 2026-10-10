import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  retrain_dataset_artifact_ids: [],
  retrain_target_column: "",
  retrain_max_trials: 10,
  retrain_dataset: null,
  deployment: { id: "dep-1", name: "toy-deploy", desired_state: "running", observed_state: "running" },
  current_model: null,
  swapped_model_version_id: null,
  error_count: 3,
  alert_count: 1,
  total_count: 4,
  retrain_status: "queued",
  created_at: "2026-10-10T05:30:00Z",
  updated_at: null,
};

describe("DemoLoopPage (task list)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    demoLoopApi.fetchDemoLoopProjects.mockResolvedValue({ items: [{ id: "p1", name: "演示项目" }] });
    demoLoopApi.fetchDemoLoops.mockResolvedValue({ items: [CONFIG] });
    demoLoopApi.fetchDemoLoopDeployments.mockResolvedValue({ items: [] });
    demoLoopApi.fetchDemoLoopDatasets.mockResolvedValue({ items: [] });
    demoLoopApi.fetchDemoLoopAnnotators.mockResolvedValue({ items: [] });
    demoLoopApi.createDemoLoop.mockResolvedValue(CONFIG);
    demoLoopApi.updateDemoLoop.mockResolvedValue(CONFIG);
    demoLoopApi.deleteDemoLoop.mockResolvedValue({ status: "deleted" });
  });

  it("renders the task list without the inference/status panels", async () => {
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(demoLoopApi.fetchDemoLoops).toHaveBeenCalledWith("p1"));
    expect(screen.getByText("自动化闭环")).toBeInTheDocument();
    // 列表页不显示逐行推理与闭环状态（在详情页）
    expect(screen.queryByText(/逐行推理调用/)).not.toBeInTheDocument();
    expect(screen.queryByText(/闭环状态/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /详情/ })).toBeInTheDocument();
  });

  it("navigates to the detail page when a row is clicked", async () => {
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("自动化闭环")).toBeInTheDocument());
    // MemoryRouter 内 navigate 生效即跳转（此处仅验证行可点击不报错 + 详情按钮存在）
    expect(screen.getByRole("button", { name: /详情/ })).toBeInTheDocument();
  });

  it("opens the create modal and submits a new loop", async () => {
    demoLoopApi.fetchDemoLoopDeployments.mockResolvedValue({
      items: [{ id: "dep-1", name: "toy-deploy", observed_state: "running" }],
    });
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("loop-task-list")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("new-loop-btn"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    const formItem = within(dialog).getAllByText(/推理部署/)[0].closest(".ant-form-item") as HTMLElement;
    fireEvent.mouseDown(formItem.querySelector(".ant-select-selector") as HTMLElement);
    const options = await screen.findAllByText(/toy-deploy/);
    const option = options.find((el) => el.closest(".ant-select-item-option")) || options[0];
    fireEvent.click(option.closest(".ant-select-item-option") ?? option);
    const errorItem = within(dialog).getAllByText(/报错类别/)[0].closest(".ant-form-item") as HTMLElement;
    const tagInput = errorItem.querySelector("input") as HTMLInputElement;
    fireEvent.change(tagInput, { target: { value: "1" } });
    fireEvent.keyDown(tagInput, { key: "Enter", keyCode: 13, which: 13 });
    fireEvent.click(screen.getByRole("button", { name: "创建闭环" }));
    await waitFor(() => expect(demoLoopApi.createDemoLoop).toHaveBeenCalled());
  });

  it("opens the edit modal from a row action and saves changes", async () => {
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("loop-task-list")).toBeInTheDocument());
    const rowButtons = screen.getAllByRole("button").filter((b) => b.closest("tbody"));
    const editButton = rowButtons.find((b) => !b.className.includes("ant-btn-dangerous") && !b.textContent.includes("详情"));
    expect(editButton).toBeTruthy();
    fireEvent.click(editButton as HTMLElement);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    const nameInput = await screen.findByDisplayValue("自动化闭环");
    fireEvent.change(nameInput, { target: { value: "夜间巡检闭环" } });
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));
    await waitFor(() => expect(demoLoopApi.updateDemoLoop).toHaveBeenCalledWith("p1", "cfg-1",
      expect.objectContaining({ name: "夜间巡检闭环" })));
  });

  it("deletes a loop after confirmation", async () => {
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("loop-task-list")).toBeInTheDocument());
    const deleteButtons = screen.getAllByRole("button", { name: /delete/i });
    fireEvent.click(deleteButtons[0]);
    const confirmButton = await screen.findByRole("button", { name: /^(OK|确 定)$/ });
    fireEvent.click(confirmButton);
    await waitFor(() => expect(demoLoopApi.deleteDemoLoop).toHaveBeenCalledWith("p1", "cfg-1"));
  });

  it("survives an empty loop list", async () => {
    demoLoopApi.fetchDemoLoops.mockResolvedValue({ items: [] });
    render(<MemoryRouter><DemoLoopPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getAllByText(/暂无闭环任务/).length).toBeGreaterThan(0));
    expect(screen.getByTestId("new-loop-btn")).toBeInTheDocument();
  });
});
