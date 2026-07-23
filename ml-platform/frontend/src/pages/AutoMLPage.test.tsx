import { render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { describe, expect, it, vi } from "vitest";

import AutoMLPage from "./AutoMLPage";

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get: vi.fn().mockRejectedValue(new Error("offline")), post: vi.fn() } }));
vi.mock("../api/datasets", () => ({ listDatasets: vi.fn(), getDatasetPreview: vi.fn() }));
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
  it("renders its controls when initial project loading fails", async () => {
    render(<AntApp><AutoMLPage /></AntApp>);

    expect(await screen.findByText("AutoML")).toBeInTheDocument();
    expect(screen.getByText("Run")).toBeInTheDocument();
  });
});
