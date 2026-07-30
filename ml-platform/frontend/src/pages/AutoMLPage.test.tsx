import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import AutoMLPage from "./AutoMLPage";

const quality = vi.hoisted(() => ({ createQualityRun: vi.fn(), getQualityRun: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get: vi.fn().mockResolvedValue({ data: { items: [{ id: "project-1", name: "Weld line", project_role: "owner" }] } }), post: vi.fn() } }));
vi.mock("../api/datasets", () => ({ listDatasets: vi.fn().mockResolvedValue([{ id: "dataset-1", name: "weld.csv", format: "csv" }]), getDatasetPreview: vi.fn().mockResolvedValue({ columns: [], preview: [] }) }));
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
    }));
  });
});
