import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TrainingJobsPage from "./TrainingJobsPage";

const mocks = vi.hoisted(() => ({
  createExperiment: vi.fn(),
  deleteExperiment: vi.fn(),
  listExperiments: vi.fn(),
  listExperimentRuns: vi.fn(),
  compareExperimentRuns: vi.fn(),
  listTrainingJobs: vi.fn(),
  getTrainingJob: vi.fn(),
  createTrainingJob: vi.fn(),
  deleteTrainingJob: vi.fn(),
  listTrainingCheckpoints: vi.fn(),
  stopTrainingJob: vi.fn(),
  resumeTrainingJob: vi.fn(),
  createTensorBoardSession: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    language: "en",
    t: {
      common: { create: "Create", error: "Error", no_data: "No data", refresh: "Refresh", confirm: "Confirm", cancel: "Cancel", delete: "Delete", success: "Success" },
      training: {
        title: "Training operations", experiments: "Experiments", jobs: "Training jobs",
        new_experiment: "New experiment", experiment_name: "Experiment name", description: "Description",
        runs: "Runs", compare: "Compare", new_job: "New training", details: "Details",
        dataset_artifact: "Dataset artifact", model_artifact: "Model artifact", model_library: "Model library",
        status: "Status", metrics: "Metrics", operator: "Operator", started: "Started", stop: "Stop",
        confirm_stop: "Confirm stop", resume: "Resume", tensorboard: "TensorBoard", checkpoints: "Checkpoints",
        epoch: "Epoch", progress: "Progress", name: "Name", project: "Project", target_column: "Target column",
      },
      model: { actions: "Actions" },
    },
  }),
}));
vi.mock("../api/experiments", () => ({
  createExperiment: mocks.createExperiment,
  deleteExperiment: mocks.deleteExperiment,
  listExperiments: mocks.listExperiments,
  listExperimentRuns: mocks.listExperimentRuns,
  compareExperimentRuns: mocks.compareExperimentRuns,
}));
vi.mock("../api/training", () => ({
  listTrainingJobs: mocks.listTrainingJobs,
  getTrainingJob: mocks.getTrainingJob,
  createTrainingJob: mocks.createTrainingJob,
  deleteTrainingJob: mocks.deleteTrainingJob,
  listTrainingCheckpoints: mocks.listTrainingCheckpoints,
  stopTrainingJob: mocks.stopTrainingJob,
  resumeTrainingJob: mocks.resumeTrainingJob,
  createTensorBoardSession: mocks.createTensorBoardSession,
}));
vi.mock("../api/client", () => ({
  default: {
    get: vi.fn().mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "p1", name: "Weld line" }] } });
      return Promise.resolve({ data: { items: [] } });
    }),
  },
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("echarts-for-react", () => ({ default: () => <div data-testid="metric-chart" /> }));

describe("TrainingJobsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listExperiments.mockResolvedValue([{
      id: "e1", project_id: "p1", created_by: "u1", name: "Weld baseline", description: "",
      mlflow_experiment_id: "m1", created_at: "2026-07-17", updated_at: "2026-07-17", run_count: 2,
    }]);
    mocks.listExperimentRuns.mockResolvedValue({ items: [
      { run_id: "run-a", experiment_id: "m1", run_name: "A", status: "FINISHED", start_time: 1, end_time: 2, artifact_uri: null, params: {}, metrics: { val_accuracy: 0.91 }, tags: {}, parent_run_id: null },
      { run_id: "run-b", experiment_id: "m1", run_name: "B", status: "FINISHED", start_time: 1, end_time: 2, artifact_uri: null, params: {}, metrics: { val_accuracy: 0.94 }, tags: {}, parent_run_id: null },
    ], total: 2 });
    mocks.compareExperimentRuns.mockResolvedValue({
      run_ids: ["run-a", "run-b"], param_names: [], metric_names: ["val_accuracy"],
      runs: [
        { run_id: "run-a", metrics: { val_accuracy: 0.91 }, params: {}, metric_history: { val_accuracy: [{ key: "val_accuracy", value: 0.91, timestamp: 1, step: 1 }] }, missing: { params: [], metrics: [] } },
        { run_id: "run-b", metrics: { val_accuracy: 0.94 }, params: {}, metric_history: { val_accuracy: [{ key: "val_accuracy", value: 0.94, timestamp: 1, step: 1 }] }, missing: { params: [], metrics: [] } },
      ],
    });
    mocks.listTrainingJobs.mockResolvedValue([
      { id: "job-1", name: "running-job", status: "running", current_epoch: 2, total_epochs: 10 },
      { id: "job-2", name: "completed-job", status: "completed", current_epoch: 10, total_epochs: 10, mlflow_run_id: "run-b" },
    ]);
    mocks.listTrainingCheckpoints.mockResolvedValue([
      { path: "checkpoints/best.joblib", uri: "mlflow-artifacts:/best", is_dir: false, file_size: 128 },
    ]);
    mocks.createTensorBoardSession.mockResolvedValue({ url: "/api/training/tensorboard/token/" });
    mocks.stopTrainingJob.mockResolvedValue({});
    mocks.resumeTrainingJob.mockResolvedValue({});
    mocks.createExperiment.mockResolvedValue({ id: "e2" });
  });

  it("creates an Experiment and compares two selected Runs", async () => {
    render(<TrainingJobsPage />);
    expect(await screen.findByRole("tab", { name: "Experiments" })).toBeInTheDocument();
    expect(await screen.findByText("Weld baseline")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "New experiment" }));
    fireEvent.change(screen.getByLabelText("Experiment name"), { target: { value: "New baseline" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(mocks.createExperiment).toHaveBeenCalledWith({
      project_id: "p1", name: "New baseline", description: "",
    }));

    fireEvent.click(screen.getByRole("button", { name: "Runs" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: "run-a" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "run-b" }));
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));

    expect(await screen.findByText("val_accuracy")).toBeInTheDocument();
    expect(screen.getByText("0.94")).toBeInTheDocument();
    expect(screen.getByTestId("metric-chart")).toBeInTheDocument();
  }, 10_000);

  it("stops, resumes, and opens TensorBoard through platform actions", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<TrainingJobsPage />);
    fireEvent.click(await screen.findByRole("tab", { name: "Training jobs" }));
    expect(await screen.findByText("running-job")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Stop running-job" }));
    fireEvent.click(await screen.findByText("Confirm stop"));
    await waitFor(() => expect(mocks.stopTrainingJob).toHaveBeenCalledWith("job-1"));

    fireEvent.click(screen.getByRole("button", { name: "Resume completed-job" }));
    fireEvent.click(await screen.findByRole("button", { name: "Resume checkpoints/best.joblib" }));
    await waitFor(() => expect(mocks.resumeTrainingJob).toHaveBeenCalledWith("job-2", "checkpoints/best.joblib"));

    fireEvent.click(screen.getByRole("button", { name: "TensorBoard completed-job" }));
    await waitFor(() => expect(open).toHaveBeenCalledWith("/api/training/tensorboard/token/", "_blank", "noopener,noreferrer"));
  }, 20_000);

  it("deletes Experiments and terminal Training Jobs, but not running jobs", async () => {
    mocks.deleteExperiment.mockResolvedValue(undefined);
    mocks.deleteTrainingJob.mockResolvedValue({ deleted: 1 });
    render(<TrainingJobsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Delete Weld baseline" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mocks.deleteExperiment).toHaveBeenCalledWith("e1"));

    fireEvent.click(screen.getByRole("tab", { name: "Training jobs" }));
    expect(screen.queryByRole("button", { name: "Delete running-job" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Delete completed-job" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mocks.deleteTrainingJob).toHaveBeenCalledWith("job-2"));
  });

  it("hides deletion for Experiments and Training Jobs with active training", async () => {
    mocks.listExperiments.mockResolvedValue([
      {
        id: "active-experiment", project_id: "p1", created_by: "u1", name: "Active baseline", description: "",
        mlflow_experiment_id: "active-m1", created_at: "2026-07-17", updated_at: "2026-07-17", run_count: 0,
      },
    ]);
    mocks.listTrainingJobs.mockResolvedValue([
      { id: "pending-job", experiment_id: "active-experiment", name: "pending-job", status: "pending" },
    ]);
    render(<TrainingJobsPage />);

    expect(await screen.findByText("Active baseline")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete Active baseline" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Training jobs" }));
    expect(await screen.findByText("pending-job")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete pending-job" })).not.toBeInTheDocument();
  });
});
