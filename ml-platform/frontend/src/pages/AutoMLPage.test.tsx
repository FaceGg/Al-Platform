import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import AutoMLPage from "./AutoMLPage";

const QUALITY_REPORT_COLUMNS = [
  "wld1c", "wld2c", "tipv1", "tipv2", "wres", "energy",
  "wld_spatter_strength", "wld1_spatter_strength", "wld2_spatter_strength",
  "spatterpos_wld", "spatterpos_pre", "spotdiameter", "spotposition", "spattercode",
  "cvei", "cvev", "cver", "cvep",
];

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
const datasets = vi.hoisted(() => ({ listDatasets: vi.fn(), getDatasetPreview: vi.fn() }));
const quality = vi.hoisted(() => ({
  createQualityRun: vi.fn(),
  downloadQualityArtifact: vi.fn(),
  getQualityRun: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({
  default: api,
  formatApiError: (error: any, fallback: string) => {
    const detail = error?.response?.data?.detail;
    if (detail && typeof detail === "object") {
      return `${detail.code}: ${detail.message}`;
    }
    return String(detail || fallback);
  },
}));
vi.mock("../api/datasets", () => datasets);
vi.mock("../api/spotWeldQuality", () => quality);
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      common: { error: "Error", success: "Success", loading: "Loading" },
      automl: {
        title: "AutoML", select_project: "Project", select_dataset: "Dataset",
        target: "Target", task: "Task", budget: "Budget", run: "Run", score: "Score",
      },
      training: { experiments: "Experiment", new_experiment: "New Experiment" },
      knowledge: { name: "Name" },
    },
  }),
}));

describe("AutoMLPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    datasets.listDatasets.mockReset();
    datasets.getDatasetPreview.mockReset();
    api.get.mockImplementation((url: string) => {
      if (url === "/experiments") {
        return Promise.resolve({ data: { items: [{ id: "experiment-1", name: "Experiment 1" }] } });
      }
      return Promise.resolve({ data: { items: [{ id: "project-1", name: "Weld line", project_role: "owner" }] } });
    });
    datasets.listDatasets.mockResolvedValue([{ id: "dataset-1", name: "weld.csv", format: "csv" }]);
    datasets.getDatasetPreview.mockResolvedValue({
      columns: ["feature", "force", "quality"],
      dtypes: { feature: "float64", force: "float64", quality: "int64" },
      preview: [],
    });
    quality.createQualityRun.mockReset();
    quality.downloadQualityArtifact.mockReset();
    quality.getQualityRun.mockReset();
    quality.createQualityRun.mockResolvedValue({ id: "run-1", status: "queued" });
    quality.getQualityRun.mockResolvedValue({ id: "run-1", status: "completed" });
    quality.downloadQualityArtifact.mockResolvedValue(new Blob(["report"]));
  });

  it("renders generic AutoML controls", async () => {
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "AutoML" })).toBeInTheDocument();
    expect(screen.getByText("Run")).toBeInTheDocument();
    expect(screen.queryByText("Budget")).not.toBeInTheDocument();
  });

  it("keeps the modeling task list visible before a project is selected", async () => {
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    expect(await screen.findByText("建模任务")).toBeInTheDocument();
    expect(screen.getByText("请选择项目后查看建模任务")).toBeInTheDocument();
  });

  it("renders the measured training time returned by ordinary AutoML", async () => {
    api.get.mockImplementation((url: string) => {
      if (url === "/training/jobs/job-1") return Promise.resolve({ data: {
        status: "completed",
        metrics: {
          best_model: { name: "LGB_v1", score: 0.91 },
          all_results: [{ name: "LGB_v1", score: 0.91, training_time_seconds: 1.234 }],
        },
      } });
      if (url === "/experiments") return Promise.resolve({ data: { items: [{ id: "experiment-1", name: "Experiment 1" }] } });
      return Promise.resolve({ data: { items: [{ id: "project-1", name: "Weld line", project_role: "owner" }] } });
    });
    api.post.mockResolvedValue({ data: {
      run_id: "job-1",
      best_model: { name: "LGB_v1", score: 0.91 },
      all_results: [{ name: "LGB_v1", score: 0.91, training_time_seconds: 1.234 }],
    } });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    const comboboxes = await screen.findAllByRole("combobox");
    fireEvent.mouseDown(comboboxes[0]);
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(comboboxes[1]);
    fireEvent.click(await screen.findByText("weld.csv"));
    await waitFor(() => expect(datasets.getDatasetPreview).toHaveBeenCalledWith("dataset-1"));
    fireEvent.mouseDown(comboboxes[3]);
    fireEvent.click(await screen.findByText("quality", { selector: ".ant-select-item-option-content" }));
    fireEvent.click(screen.getByRole("button", { name: "thunderbolt Run" }));

    expect(await screen.findByText("1.2s", {}, { timeout: 5000 })).toBeInTheDocument();
  });

  it("shows a unified modeling task list with ordinary and point-weld task types", async () => {
    api.get.mockImplementation((url: string) => {
      if (url === "/training/automl/jobs") return Promise.resolve({ data: [{
        id: "automl-1", project_id: "project-1", name: "general", status: "completed",
        metrics: { progress: { completed: 10, total: 10, percent: 100 } },
      }] });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [{
        id: "quality-1", status: "running", statistics: { modeling_progress: { completed: 3, total: 10, percent: 30 } },
      }] } });
      if (url === "/experiments") return Promise.resolve({ data: { items: [{ id: "experiment-1", name: "Experiment 1" }] } });
      return Promise.resolve({ data: { items: [{ id: "project-1", name: "Weld line", project_role: "owner" }] } });
    });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    fireEvent.mouseDown(await screen.findAllByRole("combobox").then((items) => items[0]));
    fireEvent.click(await screen.findByText("Weld line"));

    expect(await screen.findByText("普通建模")).toBeInTheDocument();
    expect(screen.getByText("点焊建模")).toBeInTheDocument();
    expect(screen.getByText("10/10 100%")).toBeInTheDocument();
    expect(screen.getByText("3/10 30%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新建" })).toBeInTheDocument();
  });

  it("shows the local worker restart error for a failed point-weld task", async () => {
    api.get.mockImplementation((url: string) => {
      if (url === "/training/automl/jobs") return Promise.resolve({ data: [] });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [{
        id: "quality-restarted", status: "failed",
        error_code: "QUALITY_RUN_LOCAL_WORKER_RESTARTED",
        error_details: {
          message: "Local quality worker stopped during service restart; rerun this task.",
        },
      }] } });
      if (url === "/experiments") return Promise.resolve({ data: { items: [] } });
      return Promise.resolve({ data: { items: [{ id: "project-1", name: "Weld line", project_role: "owner" }] } });
    });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    fireEvent.mouseDown(await screen.findAllByRole("combobox").then((items) => items[0]));
    fireEvent.click(await screen.findByText("Weld line"));

    expect(await screen.findByText("QUALITY_RUN_LOCAL_WORKER_RESTARTED")).toBeInTheDocument();
    expect(screen.getByText("Local quality worker stopped during service restart; rerun this task.")).toBeInTheDocument();
  });

  it("does not render ordinary AutoML jobs returned for another project", async () => {
    api.get.mockImplementation((url: string) => {
      if (url === "/training/automl/jobs") return Promise.resolve({ data: [
        { id: "automl-current", project_id: "project-1", name: "current-project-automl", status: "completed" },
        { id: "automl-other", project_id: "project-2", name: "other-project-automl", status: "completed" },
      ] });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [] } });
      if (url === "/experiments") return Promise.resolve({ data: { items: [] } });
      return Promise.resolve({ data: { items: [{ id: "project-1", name: "Weld line", project_role: "owner" }] } });
    });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    fireEvent.mouseDown(await screen.findAllByRole("combobox").then((items) => items[0]));
    fireEvent.click(await screen.findByText("Weld line"));

    expect(await screen.findByText("current-project-automl")).toBeInTheDocument();
    expect(screen.queryByText("other-project-automl")).not.toBeInTheDocument();
  });

  it("submits the selected generic cross-validation configuration without a budget", async () => {
    api.post.mockRejectedValue({ response: { data: { detail: "Error" } } });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    const comboboxes = await screen.findAllByRole("combobox");
    fireEvent.mouseDown(comboboxes[0]);
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(comboboxes[1]);
    fireEvent.click(await screen.findByText("weld.csv"));
    await waitFor(() => expect(datasets.getDatasetPreview).toHaveBeenCalledWith("dataset-1"));
    fireEvent.mouseDown(comboboxes[3]);
    fireEvent.click(await screen.findByText("quality", { selector: ".ant-select-item-option-content" }));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "交叉验证折数" }));
    fireEvent.click(await screen.findByText("3 折"));
    fireEvent.click(screen.getByRole("button", { name: "thunderbolt Run" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/training/automl/run", expect.objectContaining({
      cross_validation_enabled: true,
      cross_validation_folds: 3,
    })));
    expect(api.post.mock.calls[0][1]).not.toHaveProperty("time_budget");
  });

  it("submits holdout evaluation when generic cross-validation is disabled", async () => {
    api.post.mockRejectedValue({ response: { data: { detail: "Error" } } });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    const comboboxes = await screen.findAllByRole("combobox");
    fireEvent.mouseDown(comboboxes[0]);
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(comboboxes[1]);
    fireEvent.click(await screen.findByText("weld.csv"));
    await waitFor(() => expect(datasets.getDatasetPreview).toHaveBeenCalledWith("dataset-1"));
    fireEvent.mouseDown(comboboxes[3]);
    fireEvent.click(await screen.findByText("quality", { selector: ".ant-select-item-option-content" }));
    fireEvent.click(screen.getByRole("switch", { name: "启用交叉验证" }));
    fireEvent.click(screen.getByRole("button", { name: "thunderbolt Run" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/training/automl/run", expect.objectContaining({
      cross_validation_enabled: false,
      cross_validation_folds: null,
    })));
  });

  it("exposes ten algorithm candidates for generic AutoML", async () => {
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "算法集合" }));

    for (const label of [
      "LGB_v1 · LightGBM", "LGB_v2 · LightGBM", "XGB_v1 · XGBoost", "XGB_v2 · XGBoost",
      "CAT_v1 · CatBoost", "CAT_v2 · CatBoost", "GBDT_v1 · GBDT", "RF_v1 · Random Forest",
      "ET_v1 · Extra Trees", "HGB_v1 · HistGradientBoosting",
    ]) {
      expect(await screen.findByText(label, { selector: ".ant-select-item-option-content" })).toBeInTheDocument();
    }
  });

  it("starts a quality run from the spot-weld quality recipe", async () => {
    datasets.getDatasetPreview.mockResolvedValue({
      columns: QUALITY_REPORT_COLUMNS,
      dtypes: Object.fromEntries(QUALITY_REPORT_COLUMNS.map((column) => [column, "float64"])),
      preview: [],
    });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: "点焊质量感知" }));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "质量感知项目" }));
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "质量感知数据" }));
    fireEvent.click(await screen.findByText("weld.csv"));
    await waitFor(() => expect(datasets.getDatasetPreview).toHaveBeenCalledWith("dataset-1"));
    fireEvent.click(screen.getByRole("button", { name: "运行质量感知" }));

    await waitFor(() => expect(quality.createQualityRun).toHaveBeenCalledWith("project-1", {
      dataset_artifact_id: "dataset-1",
      field_mapping: {},
      candidate_ids: [],
      target_column: undefined,
      input_columns: QUALITY_REPORT_COLUMNS,
      cross_validation_enabled: true,
      cross_validation_folds: 3,
    }));
  });

  it("blocks a report-incompatible dataset before it submits a quality run", async () => {
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: "点焊质量感知" }));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "质量感知项目" }));
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "质量感知数据" }));
    fireEvent.click(await screen.findByText("weld.csv"));
    await waitFor(() => expect(datasets.getDatasetPreview).toHaveBeenCalledWith("dataset-1"));

    const runButton = screen.getByRole("button", { name: "运行质量感知" });
    expect(runButton).toBeDisabled();
    fireEvent.click(runButton);
    expect(quality.createQualityRun).not.toHaveBeenCalled();
  });

  it("disables quality runs while the newly selected dataset preview is pending", async () => {
    datasets.listDatasets.mockResolvedValue([
      { id: "dataset-1", name: "weld.csv", format: "csv" },
      { id: "dataset-2", name: "other.csv", format: "csv" },
    ]);
    let resolveSecondPreview: ((value: unknown) => void) | undefined;
    const secondPreview = new Promise((resolve) => {
      resolveSecondPreview = resolve;
    });
    datasets.getDatasetPreview.mockImplementation((datasetId: string) => {
      if (datasetId === "dataset-1") {
        return Promise.resolve({
          columns: QUALITY_REPORT_COLUMNS,
          dtypes: Object.fromEntries(QUALITY_REPORT_COLUMNS.map((column) => [column, "float64"])),
          preview: [],
        });
      }
      return secondPreview;
    });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: "点焊质量感知" }));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "质量感知项目" }));
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "质量感知数据" }));
    fireEvent.click(await screen.findByText("weld.csv"));
    await waitFor(() => expect(datasets.getDatasetPreview).toHaveBeenCalledWith("dataset-1"));
    await waitFor(() => expect(screen.getByRole("button", { name: "运行质量感知" })).not.toBeDisabled());

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "质量感知数据" }));
    fireEvent.click(await screen.findByText("other.csv"));

    expect(screen.getByRole("button", { name: "运行质量感知" })).toBeDisabled();
    resolveSecondPreview?.({ columns: [], dtypes: {}, preview: [] });
  });

  it("configures the quality recipe target, inputs, cross-validation, and full report download", async () => {
    datasets.getDatasetPreview.mockResolvedValue({
      columns: [...QUALITY_REPORT_COLUMNS, "quality"],
      dtypes: Object.fromEntries([...QUALITY_REPORT_COLUMNS, "quality"].map((column) => [column, "float64"])),
      preview: [],
    });
    quality.getQualityRun.mockResolvedValue({
      id: "run-1",
      status: "completed",
      target_column: "quality",
      input_columns: ["feature", "force"],
      evaluation: { cross_validation_enabled: true, cross_validation_folds: 4 },
      output_artifacts: { report: "report-artifact-1" },
      automl_results: [{ name: "LGB_v1", auc: 0.91, f1: 0.87 }],
    });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: "点焊质量感知" }));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "质量感知项目" }));
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "质量感知数据" }));
    fireEvent.click(await screen.findByText("weld.csv"));
    await waitFor(() => expect(datasets.getDatasetPreview).toHaveBeenCalledWith("dataset-1"));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "质量感知目标列" }));
    expect(screen.queryByText("wld1c", { selector: ".ant-select-item-option-content" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByText("quality", { selector: ".ant-select-item-option-content" }));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "质量感知交叉验证折数" }));
    fireEvent.click(await screen.findByText("4 折"));
    fireEvent.click(screen.getByRole("button", { name: "运行质量感知" }));

    await waitFor(() => expect(quality.createQualityRun).toHaveBeenCalledWith("project-1", {
      dataset_artifact_id: "dataset-1",
      field_mapping: {},
      candidate_ids: [],
      target_column: "quality",
      input_columns: QUALITY_REPORT_COLUMNS,
      cross_validation_enabled: true,
      cross_validation_folds: 4,
    }));
    const download = await screen.findByRole("button", { name: "下载完整报告" });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    fireEvent.click(download);
    await waitFor(() => expect(quality.downloadQualityArtifact).toHaveBeenCalledWith("project-1", "run-1", "report"));
  });

  it("submits the selected report candidate IDs in order", async () => {
    datasets.getDatasetPreview.mockResolvedValue({
      columns: QUALITY_REPORT_COLUMNS,
      dtypes: Object.fromEntries(QUALITY_REPORT_COLUMNS.map((column) => [column, "float64"])),
      preview: [],
    });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: "点焊质量感知" }));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "质量感知项目" }));
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "质量感知数据" }));
    fireEvent.click(await screen.findByText("weld.csv"));
    await waitFor(() => expect(datasets.getDatasetPreview).toHaveBeenCalledWith("dataset-1"));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "报告候选算法" }));
    fireEvent.click(await screen.findByText("RF_v1"));
    fireEvent.click(await screen.findByText("GBDT_v1"));
    fireEvent.click(screen.getByRole("button", { name: "运行质量感知" }));

    await waitFor(() => expect(quality.createQualityRun).toHaveBeenCalledWith("project-1", {
      dataset_artifact_id: "dataset-1",
      field_mapping: {},
      candidate_ids: ["RF_v1", "GBDT_v1"],
      target_column: undefined,
      input_columns: QUALITY_REPORT_COLUMNS,
      cross_validation_enabled: true,
      cross_validation_folds: 3,
    }));
  });

  it("keeps AutoML visible when a structured dispatch error is returned", async () => {
    api.post.mockRejectedValue({
      response: {
        data: {
          detail: {
            code: "TRAINING_DISPATCH_FAILED",
            message: "Training task could not be queued",
          },
        },
      },
    });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    const comboboxes = await screen.findAllByRole("combobox");
    fireEvent.mouseDown(comboboxes[0]);
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(comboboxes[1]);
    fireEvent.click(await screen.findByText("weld.csv"));
    await waitFor(() => expect(datasets.getDatasetPreview).toHaveBeenCalledWith("dataset-1"));
    fireEvent.mouseDown(comboboxes[3]);
    fireEvent.click(await screen.findByText("quality", { selector: ".ant-select-item-option-content" }));
    fireEvent.click(screen.getByRole("button", { name: "thunderbolt Run" }));

    expect(await screen.findByText("TRAINING_DISPATCH_FAILED: Training task could not be queued")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AutoML" })).toBeInTheDocument();
  });

  it("submits the selected AutoML candidate IDs", async () => {
    api.post.mockRejectedValue({ response: { data: { detail: "Error" } } });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    const comboboxes = await screen.findAllByRole("combobox");
    fireEvent.mouseDown(comboboxes[0]);
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(comboboxes[1]);
    fireEvent.click(await screen.findByText("weld.csv"));
    await waitFor(() => expect(datasets.getDatasetPreview).toHaveBeenCalledWith("dataset-1"));
    fireEvent.mouseDown(comboboxes[3]);
    fireEvent.click(await screen.findByText("quality", { selector: ".ant-select-item-option-content" }));

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "算法集合" }));
    fireEvent.click(await screen.findByText("LGB_v1 · LightGBM"));
    fireEvent.click(screen.getByRole("button", { name: "thunderbolt Run" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/training/automl/run", expect.objectContaining({
      candidate_ids: ["LGB_v1"],
    })));
  });

  it("submits the selected input columns with the target column", async () => {
    api.post.mockRejectedValue({ response: { data: { detail: "Error" } } });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    const comboboxes = await screen.findAllByRole("combobox");
    fireEvent.mouseDown(comboboxes[0]);
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(comboboxes[1]);
    fireEvent.click(await screen.findByText("weld.csv"));
    await waitFor(() => expect(datasets.getDatasetPreview).toHaveBeenCalledWith("dataset-1"));
    fireEvent.mouseDown(comboboxes[3]);
    fireEvent.click(await screen.findByText("quality", { selector: ".ant-select-item-option-content" }));

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "输入列" }));
    const forceOptions = await screen.findAllByText("force", { selector: ".ant-select-item-option-content" });
    fireEvent.click(forceOptions[forceOptions.length - 1]);
    fireEvent.click(screen.getByRole("button", { name: "thunderbolt Run" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/training/automl/run", expect.objectContaining({
      target_column: "quality",
      input_columns: ["feature"],
    })));
  });

  it("keeps the report candidate selection when switching task type", async () => {
    api.post.mockRejectedValue({ response: { data: { detail: "Error" } } });
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    const comboboxes = await screen.findAllByRole("combobox");
    fireEvent.mouseDown(comboboxes[0]);
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(comboboxes[1]);
    fireEvent.click(await screen.findByText("weld.csv"));
    await waitFor(() => expect(datasets.getDatasetPreview).toHaveBeenCalledWith("dataset-1"));
    fireEvent.mouseDown(comboboxes[3]);
    fireEvent.click(await screen.findByText("quality", { selector: ".ant-select-item-option-content" }));

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "算法集合" }));
    fireEvent.click(await screen.findByText("LGB_v1 · LightGBM"));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "任务类型" }));
    fireEvent.click(await screen.findByText("Regression"));
    fireEvent.click(screen.getByRole("button", { name: "thunderbolt Run" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/training/automl/run", expect.objectContaining({
      task: "regression",
      candidate_ids: ["LGB_v1"],
    })));
  });
});
