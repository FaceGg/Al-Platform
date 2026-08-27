import { App as AntApp, Modal } from "antd";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AutoMLTaskPage from "./AutoMLTaskPage";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const registerAutoMLResult = vi.hoisted(() => vi.fn());

vi.mock("../components/AppLayout", () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get, post }, formatApiError: (_error: unknown, fallback: string) => fallback }));
vi.mock("../api/modelRegistry", () => ({ registerAutoMLResult }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/automl/task/job-1"]}>
      <Routes><Route path="/automl/task/:taskId" element={<AntApp><AutoMLTaskPage /></AntApp>} /></Routes>
    </MemoryRouter>,
  );
}

describe("AutoMLTaskPage model registration", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    get.mockResolvedValue({ data: {
      id: "job-1",
      name: "焊点缺陷建模",
      project_id: "project-1",
      project_name: "一号焊装项目",
      experiment_name: "焊点缺陷实验",
      status: "completed",
      metrics: {
        progress: { completed: 2, total: 2, percent: 100 },
        algorithm_results: [
          { algorithm_id: "random_forest", name: "随机森林", status: "completed", model_library_id: "library-1", auc: 0.9, f1: 0.8, trials: [] },
          { algorithm_id: "gbdt", name: "梯度提升树", status: "completed", model_library_id: "library-2", auc: 0.8, f1: 0.7, trials: [] },
        ],
      },
    } });
    registerAutoMLResult.mockResolvedValue({
      created: true,
      registered_model: { id: "registered-1", project_id: "project-1", name: "焊点缺陷建模 - 随机森林", description: "", latest_version: 1, latest_approval_status: "pending", created_at: null },
      version: { id: "version-1" },
    });
    post.mockResolvedValue({ data: { preview: { overview: { project: "一号焊装项目", experiment: "焊点缺陷实验", best_model: { name: "随机森林" }, rows: 120, features: 8, best_k: 3 }, selection: [{ algorithm_id: "random_forest", name: "随机森林", score: 0.9, best_params: { n_estimators: 100 } }], clustering: { best_k: 3, silhouette: 0.61, counts: { 0: 40, 1: 50, 2: 30 } }, importance: [{ feature: "电流", importance: 0.8, weight: 0.5 }], inference: [{ actual: "合格", predicted: "合格", confidence: 0.95 }] } } });
  });

  it("shows experiment and project names instead of task name and project id", async () => {
    renderPage();

    expect(await screen.findByText("焊点缺陷实验")).toBeInTheDocument();
    expect(screen.getByText("一号焊装项目")).toBeInTheDocument();
    expect(screen.getByText("实验")).toBeInTheDocument();
    expect(screen.queryByText("任务")).not.toBeInTheDocument();
    expect(screen.queryByText("project-1")).not.toBeInTheDocument();
    expect(screen.queryByText("焊点缺陷建模")).not.toBeInTheDocument();
  });

  it("shows completed jobs at 100% when a time budget ends before all planned trials", async () => {
    get.mockResolvedValue({ data: {
      id: "job-1",
      project_id: "project-1",
      project_name: "一号焊装项目",
      experiment_name: "焊点缺陷实验",
      status: "completed",
      metrics: {
        progress: { completed: 13, total: 35, percent: 37.14, budget_exhausted: true },
        algorithm_results: [{ algorithm_id: "gbdt", name: "梯度提升树", status: "completed", model_library_id: "library-1", auc: 0.9, f1: 0.8, trials: [] }],
      },
    } });
    renderPage();

    expect(await screen.findByText("已完成试验 13 / 35")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByRole("button", { name: "生成分析报告" })).toBeEnabled();
  });

  it("places register after detail and marks only the clicked result registered", async () => {
    renderPage();

    expect(await screen.findByText("随机森林")).toBeInTheDocument();
    const registerButtons = await screen.findAllByRole("button", { name: "注册" });
    expect(registerButtons).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "详细" })[0].compareDocumentPosition(registerButtons[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    fireEvent.click(registerButtons[0]);
    await waitFor(() => expect(registerAutoMLResult).toHaveBeenCalledWith("project-1", "job-1", "random_forest"));
    expect(await screen.findByRole("button", { name: "已注册" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "注册" })).toHaveLength(1);
  });

  it("disables registration when a result has no trusted source", async () => {
    get.mockResolvedValue({ data: {
      id: "job-1", name: "任务", project_id: "project-1", status: "completed",
      metrics: { progress: { completed: 1, total: 1, percent: 100 }, algorithm_results: [{ algorithm_id: "rf", name: "RF", status: "completed" }] },
    } });
    renderPage();
    const register = await screen.findByRole("button", { name: "注册" });
    expect(register).toBeDisabled();
  });

  it("generates a five-tab preview and exports the detailed zip", async () => {
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:report");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "生成分析报告" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/training/jobs/job-1/automl-report"));
    expect(await screen.findByText("分析报告预览")).toBeInTheDocument();
    for (const label of ["总览", "AutoML选型", "聚类画像", "特征重要性", "推理结果"]) expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    get.mockResolvedValueOnce({ data: new Blob(["zip"], { type: "application/zip" }) });
    fireEvent.click(screen.getByRole("button", { name: /导出详细报告/ }));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/training/jobs/job-1/automl-report/artifacts/package", { responseType: "blob" }));
    createObjectURL.mockRestore(); revokeObjectURL.mockRestore(); click.mockRestore();
  });

  it("restores an existing report and requires confirmation before regeneration", async () => {
    const confirm = vi.spyOn(Modal, "confirm").mockReturnValue({ destroy: vi.fn(), update: vi.fn() });
    const existingReport = { preview: { overview: { project: "一号焊装项目" }, selection: [], clustering: {}, importance: [], inference: [] } };
    get.mockResolvedValue({ data: {
      id: "job-1", project_id: "project-1", project_name: "一号焊装项目", experiment_name: "焊点缺陷实验", status: "completed",
      metrics: { progress: { completed: 1, total: 1, percent: 100 }, algorithm_results: [{ algorithm_id: "rf", name: "RF", status: "completed", model_library_id: "library-1", trials: [] }], automl_report: existingReport },
    } });
    renderPage();
    expect(await screen.findByText("分析报告预览")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "生成分析报告" }));
    expect(confirm).toHaveBeenCalledWith(expect.objectContaining({ title: "分析报告已经生成过，是否重新生成？" }));
    expect(post).not.toHaveBeenCalled();
    await confirm.mock.calls[0][0].onOk?.(vi.fn());
    await waitFor(() => expect(post).toHaveBeenCalledWith("/training/jobs/job-1/automl-report?regenerate=true"));
  });

  it("shows AUC, F1, and Accuracy for every hyperparameter trial", async () => {
    get.mockResolvedValue({ data: {
      id: "job-1", project_id: "project-1", project_name: "一号焊装项目", experiment_name: "焊点缺陷实验", status: "completed",
      metrics: { progress: { completed: 1, total: 1, percent: 100 }, algorithm_results: [{ algorithm_id: "rf", name: "RF", status: "completed", model_library_id: "library-1", best_score: 0.91, trials: [{ number: 1, state: "complete", score: 0.71, accuracy: 0.71, auc: 0.93, f1: 0.82, params: {} }] }] },
    } });
    const view = renderPage();
    const resultRow = (await within(view.container).findByText("RF")).closest("tr");
    expect(resultRow).toBeTruthy();
    fireEvent.click(within(resultRow as HTMLElement).getByRole("button", { name: "详细" }));
    const detailTitle = await screen.findByText("RF 详细结果");
    const detailDialog = detailTitle.closest(".ant-modal") as HTMLElement;
    expect(detailDialog).toBeTruthy();
    expect(within(detailDialog).getAllByText("Accuracy").some((node) => node.classList.contains("ant-statistic-title"))).toBe(true);
    expect(within(detailDialog).queryByText("Best Accuracy")).not.toBeInTheDocument();
    expect(within(detailDialog).getByRole("columnheader", { name: "AUC" })).toBeInTheDocument();
    expect(within(detailDialog).getByRole("columnheader", { name: "F1" })).toBeInTheDocument();
    expect(within(detailDialog).getByRole("columnheader", { name: "Accuracy" })).toBeInTheDocument();
    expect(within(detailDialog).getByText("0.9300")).toBeInTheDocument();
    expect(within(detailDialog).getByText("0.8200")).toBeInTheDocument();
    expect(within(detailDialog).getByText("0.7100")).toBeInTheDocument();
  });
});
