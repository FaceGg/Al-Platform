import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import AutoMLPage from "./AutoMLPage";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
const datasets = vi.hoisted(() => ({ listDatasets: vi.fn(), getDatasetPreview: vi.fn() }));
const quality = vi.hoisted(() => ({ createQualityRun: vi.fn(), getQualityRun: vi.fn() }));

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
    datasets.getDatasetPreview.mockResolvedValue({ columns: ["feature", "quality"], preview: [] });
    quality.createQualityRun.mockReset();
    quality.getQualityRun.mockReset();
    quality.createQualityRun.mockResolvedValue({ id: "run-1", status: "queued" });
    quality.getQualityRun.mockResolvedValue({ id: "run-1", status: "completed" });
  });

  it("renders generic AutoML controls", async () => {
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "AutoML" })).toBeInTheDocument();
    expect(screen.getByText("Run")).toBeInTheDocument();
  });

  it("starts a quality run from the spot-weld quality recipe", async () => {
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: "点焊质量感知" }));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "质量感知项目" }));
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "质量感知数据" }));
    fireEvent.click(await screen.findByText("weld.csv"));
    fireEvent.click(screen.getByRole("button", { name: "运行质量感知" }));

    await waitFor(() => expect(quality.createQualityRun).toHaveBeenCalledWith("project-1", {
      dataset_artifact_id: "dataset-1",
      field_mapping: {},
      candidate_ids: [],
    }));
  });

  it("submits the selected report candidate IDs in order", async () => {
    render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

    fireEvent.click(await screen.findByRole("tab", { name: "点焊质量感知" }));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "质量感知项目" }));
    fireEvent.click(await screen.findByText("Weld line"));
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "质量感知数据" }));
    fireEvent.click(await screen.findByText("weld.csv"));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "报告候选算法" }));
    fireEvent.click(await screen.findByText("RF_v1"));
    fireEvent.click(await screen.findByText("GBDT_v1"));
    fireEvent.click(screen.getByRole("button", { name: "运行质量感知" }));

    await waitFor(() => expect(quality.createQualityRun).toHaveBeenCalledWith("project-1", {
      dataset_artifact_id: "dataset-1",
      field_mapping: {},
      candidate_ids: ["RF_v1", "GBDT_v1"],
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
    fireEvent.click(await screen.findByText("Logistic Regression"));
    fireEvent.click(screen.getByRole("button", { name: "thunderbolt Run" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/training/automl/run", expect.objectContaining({
      candidate_ids: ["logistic_regression"],
    })));
  });

  it("removes candidate IDs that are invalid for a new task", async () => {
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
    fireEvent.click(await screen.findByText("Logistic Regression"));
    fireEvent.mouseDown(comboboxes[4]);
    fireEvent.click(await screen.findByText("Regression"));
    fireEvent.click(screen.getByRole("button", { name: "thunderbolt Run" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/training/automl/run", expect.objectContaining({
      task: "regression",
      candidate_ids: [],
    })));
  });
});
