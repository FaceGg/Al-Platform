import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TrainingJobsPage from "./TrainingJobsPage";

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      common: { create: "Create", error: "Error", no_data: "No data", refresh: "Refresh" },
      training: {
        title: "Training", new_job: "New training", details: "Details", dataset_artifact: "Dataset artifact",
        model_artifact: "Model artifact", model_library: "Model library", status: "Status", metrics: "Metrics",
        operator: "Operator", started: "Started",
      },
      model: { actions: "Actions" },
    },
  }),
}));
vi.mock("../api/training", () => ({
  listTrainingJobs: vi.fn().mockResolvedValue([{
    id: "job-1", name: "weld", status: "completed", dataset_artifact_id: "dataset-1",
    model_artifact_id: "model-1", model_library_id: "library-1", metrics: { accuracy: 0.95 },
  }]),
  getTrainingJob: vi.fn().mockResolvedValue({
    id: "job-1", name: "weld", dataset_artifact_id: "dataset-1",
    model_artifact_id: "model-1", model_library_id: "library-1",
  }),
  createTrainingJob: vi.fn(),
}));
vi.mock("../api/client", () => ({
  default: { get: vi.fn().mockResolvedValue({ data: { items: [] } }) },
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));

describe("TrainingJobsPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("offers artifact-based training and exposes lineage details", async () => {
    render(<TrainingJobsPage />);
    expect(await screen.findByRole("button", { name: /new training/i })).toBeInTheDocument();
    expect(await screen.findByText("weld")).toBeInTheDocument();
    screen.getByRole("button", { name: /details/i }).click();
    await waitFor(() => expect(screen.getByText("dataset-1")).toBeInTheDocument());
    expect(screen.getByText("model-1")).toBeInTheDocument();
    expect(screen.getByText("library-1")).toBeInTheDocument();
  });
});
