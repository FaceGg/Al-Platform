import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentModelingWizard from "./AgentModelingWizard";

const apiClientGet = vi.hoisted(() => vi.fn());
const apiClientPost = vi.hoisted(() => vi.fn());
const datasetMocks = vi.hoisted(() => ({
  listDatasets: vi.fn(),
  getDatasetPreview: vi.fn(),
}));

vi.mock("../api/client", () => ({
  default: { get: apiClientGet, post: apiClientPost },
}));
vi.mock("../api/datasets", () => datasetMocks);
vi.mock("../pages/AutoMLPage", () => ({
  AUTOML_ALGORITHM_IDS: ["lightgbm", "xgboost", "mlp"],
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({ lang: "zh", t: {}, setLang: () => {} }),
}));

function renderWizard() {
  return render(
    <MemoryRouter>
      <AntApp><AgentModelingWizard /></AntApp>
    </MemoryRouter>,
  );
}

describe("AgentModelingWizard", () => {
  beforeEach(() => {
    localStorage.clear();
    apiClientGet.mockReset().mockImplementation((url: string) => {
      if (url === "/projects") {
        return Promise.resolve({ data: { items: [{ id: "p1", name: "拧紧产线" }] } });
      }
      return Promise.resolve({ data: {} });
    });
    datasetMocks.listDatasets.mockReset().mockResolvedValue([
      { id: "d1", name: "tighten_train.csv" },
      { id: "d2", name: "weld.csv" },
    ]);
    datasetMocks.getDatasetPreview.mockReset().mockImplementation((id: string) => {
      if (id === "d1") {
        return Promise.resolve({
          columns: ["ACTUAL_TORQUE", "TARGET_TORQUE", "DECIDE(判定（最终判定）（0-不合格，1-合格）)"],
        });
      }
      return Promise.resolve({ columns: ["a", "b", "label"] });
    });
    apiClientPost.mockReset();
  });

  it("walks the four steps and submits an experiment plus an automl run", async () => {
    renderWizard();

    // Step 1: project + dataset.
    fireEvent.change(await screen.findByLabelText("选择项目"), { target: { value: "p1" } });
    fireEvent.change(await screen.findByLabelText("选择数据集"), { target: { value: "d1" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));

    // Step 2: the preferred DECIDE target is auto-selected; inputs = other columns.
    expect(await screen.findByText(/2 列/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));

    // Step 3: default medium strength; keep defaults.
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));

    // Step 4: confirm summary then launch.
    expect(await screen.findByText(/拧紧产线/)).toBeInTheDocument();
    expect(screen.getByText(/tighten_train\.csv/)).toBeInTheDocument();
    apiClientPost.mockImplementation((url: string) => {
      if (url === "/experiments") return Promise.resolve({ data: { id: "e1" } });
      if (url === "/training/automl/run") return Promise.resolve({ data: { run_id: "r1" } });
      return Promise.resolve({ data: {} });
    });
    fireEvent.click(screen.getByRole("button", { name: /启动全自动建模/ }));

    await waitFor(() => expect(apiClientPost).toHaveBeenCalledTimes(2));
    const runCall = apiClientPost.mock.calls.find(([url]) => url === "/training/automl/run");
    expect(runCall).toBeTruthy();
    const payload = runCall![1];
    expect(payload.project_id).toBe("p1");
    expect(payload.experiment_id).toBe("e1");
    expect(payload.dataset_artifact_id).toBe("d1");
    expect(payload.target_column).toContain("判定");
    expect(payload.input_columns).toEqual(["ACTUAL_TORQUE", "TARGET_TORQUE"]);
    expect(payload.search_strength).toBe("medium");
    expect(payload.time_budget).toBe(3600);
    expect(payload.algorithm_ids).toEqual(["lightgbm", "xgboost", "mlp"]);
  });

  it("keeps the next button disabled until project and dataset are chosen", async () => {
    renderWizard();

    const next = await screen.findByRole("button", { name: /下一步/ });
    expect(next).toBeDisabled();
    fireEvent.change(screen.getByLabelText("选择项目"), { target: { value: "p1" } });
    await waitFor(() => expect(screen.getByLabelText("选择数据集")).not.toBeDisabled());
    expect(next).toBeDisabled();
    fireEvent.change(screen.getByLabelText("选择数据集"), { target: { value: "d1" } });
    await waitFor(() => expect(next).not.toBeDisabled());
  });

  it("surfaces the empty-dataset hint when a project has no datasets", async () => {
    datasetMocks.listDatasets.mockResolvedValue([]);
    renderWizard();

    fireEvent.change(await screen.findByLabelText("选择项目"), { target: { value: "p1" } });
    expect(await screen.findByText(/暂无数据集/)).toBeInTheDocument();
  });

  it("surfaces submission errors without losing the summary", async () => {
    renderWizard();
    fireEvent.change(await screen.findByLabelText("选择项目"), { target: { value: "p1" } });
    fireEvent.change(await screen.findByLabelText("选择数据集"), { target: { value: "d1" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await screen.findByText(/2 列/);
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    apiClientPost.mockRejectedValueOnce({ response: { data: { detail: "quota" } } });
    fireEvent.click(await screen.findByRole("button", { name: /启动全自动建模/ }));

    expect(await screen.findByText(/quota/)).toBeInTheDocument();
    expect(screen.getByText(/拧紧产线/)).toBeInTheDocument();
  });
});
