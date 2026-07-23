import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ModelLibraryPage from "./ModelLibraryPage";

const mocks = vi.hoisted(() => ({
  listRegisteredModels: vi.fn(), createRegisteredModel: vi.fn(), listModelVersions: vi.fn(),
  registerPlatformVersion: vi.fn(), approveModelVersion: vi.fn(), rejectModelVersion: vi.fn(),
  listDeployments: vi.fn(), createDeployment: vi.fn(), startDeployment: vi.fn(),
  stopDeployment: vi.fn(), predictDeployment: vi.fn(), deleteRegisteredModel: vi.fn(), deleteDeployment: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/modelRegistry", () => mocks);
vi.mock("../api/client", () => ({
  default: { get: vi.fn().mockResolvedValue({ data: { items: [
    { id: "p1", name: "Weld line", project_role: "owner" },
    { id: "p2", name: "Read only", project_role: "viewer" },
  ] } }) },
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("../i18n", () => ({ useI18n: () => ({ t: {
  common: { create: "Create", cancel: "Cancel", delete: "Delete", refresh: "Refresh", close: "Close" },
  model: { actions: "Actions" },
  modelRegistry: {
    title: "Model operations", project: "Project", selectProject: "Select project",
    models: "Registered models", deployments: "Deployments", name: "Name", description: "Description",
    latestVersion: "Latest version", status: "Status", versions: "Versions", register: "Register model",
    sourceLibraryId: "Source model ID", registerVersion: "Register version", approve: "Approve",
    reject: "Reject", comment: "Comment", createDeployment: "Create deployment",
    version: "Version", desiredState: "Desired", observedState: "Observed", start: "Start",
    stop: "Stop", onlineTest: "Online test", recordsJson: "JSON records", predict: "Predict",
    predictions: "Predictions", probabilities: "Probabilities", duration: "Duration", emptyModels: "No registered models",
    emptyDeployments: "No deployments", selectHint: "Select a project", loadFailed: "Load failed",
    commandFailed: "Command failed", runtimeFailed: "Runtime failed", permissionDenied: "Permission denied",
    pending: "Pending", approved: "Approved", rejected: "Rejected", archived: "Archived",
    running: "Running", stopped: "Stopped", starting: "Starting", stopping: "Stopping", failed: "Failed",
  },
} }) }));

const version = {
  id: "v1", registered_model_id: "m1", version_number: 1, source_kind: "platform_joblib",
  framework: "scikit-learn", algorithm: "LogisticRegression",
  feature_schema: [{ name: "current", dtype: "float64" }, { name: "voltage", dtype: "float64" }],
  output_schema: { name: "fault", dtype: "int64", task: "classification" }, metrics: {},
  conversion_metadata: {}, approval_status: "pending", approval_comment: "", created_at: null,
};
const deployment = {
  id: "d1", project_id: "p1", name: "line-a", model_version_id: "v1",
  desired_state: "stopped", observed_state: "stopped", last_error_code: null,
  last_checked_at: null, created_at: null,
};

describe("ModelLibraryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listRegisteredModels.mockResolvedValue([{ id: "m1", project_id: "p1", name: "Weld fault", description: "", latest_version: null, latest_approval_status: null, created_at: null }]);
    mocks.listModelVersions.mockResolvedValue([]);
    mocks.listDeployments.mockResolvedValue([]);
    mocks.createRegisteredModel.mockResolvedValue({ id: "m1" });
    mocks.registerPlatformVersion.mockResolvedValue(version);
    mocks.approveModelVersion.mockResolvedValue({ ...version, approval_status: "approved" });
    mocks.createDeployment.mockResolvedValue(deployment);
    mocks.startDeployment.mockResolvedValue({ ...deployment, desired_state: "running", observed_state: "running" });
    mocks.stopDeployment.mockResolvedValue(deployment);
    mocks.predictDeployment.mockResolvedValue({ deployment_id: "d1", model_version_id: "v1", version_number: 1, predictions: [1], probabilities: [[0.08, 0.92]], duration_ms: 2.4 });
  });

  it("registers, approves, deploys, starts, and predicts named records", async () => {
    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Weld line (owner)"));
    expect(await screen.findByText("Weld fault")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Register version Weld fault" }));
    fireEvent.change(screen.getByLabelText("Source model ID"), { target: { value: "library-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Register version" }));
    await waitFor(() => expect(mocks.registerPlatformVersion).toHaveBeenCalledWith("m1", "library-1"));

    fireEvent.click(screen.getByRole("button", { name: "Versions Weld fault" }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve version 1" }));
    await waitFor(() => expect(mocks.approveModelVersion).toHaveBeenCalledWith("v1", ""));

    fireEvent.click(screen.getByRole("tab", { name: "Deployments" }));
    fireEvent.click(screen.getByRole("button", { name: "Create deployment" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "line-a" } });
    fireEvent.mouseDown(screen.getByLabelText("Version"));
    fireEvent.click(await screen.findByText(/Weld fault.*v1/));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(mocks.createDeployment).toHaveBeenCalledWith("p1", { name: "line-a", model_version_id: "v1" }));

    fireEvent.click(await screen.findByRole("button", { name: "Start line-a" }));
    await waitFor(() => expect(mocks.startDeployment).toHaveBeenCalledWith("d1"));
    fireEvent.click(screen.getByRole("button", { name: "Online test line-a" }));
    const recordsInput = await screen.findByLabelText("JSON records");
    expect((recordsInput as HTMLTextAreaElement).value).toContain('"current"');
    expect((recordsInput as HTMLTextAreaElement).value).toContain('"voltage"');
    fireEvent.change(recordsInput, { target: { value: '[{"current":1.2,"voltage":3.4}]' } });
    fireEvent.click(screen.getByRole("button", { name: "Predict" }));
    await waitFor(() => expect(mocks.predictDeployment).toHaveBeenCalledWith("d1", [{ current: 1.2, voltage: 3.4 }]));
    expect(await screen.findByText(/0\.92/)).toBeInTheDocument();
    expect(screen.getByText("2.4 ms")).toBeInTheDocument();
    expect(screen.getAllByText("v1").length).toBeGreaterThan(0);
  }, 15_000);

  it("keeps viewer read-only and shows runtime failure state", async () => {
    mocks.listDeployments.mockResolvedValue([{ ...deployment, observed_state: "failed", last_error_code: "MODEL_LOAD_FAILED" }]);
    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Read only (viewer)"));
    fireEvent.click(screen.getByRole("tab", { name: "Deployments" }));
    expect(await screen.findByText("MODEL_LOAD_FAILED")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create deployment" })).not.toBeInTheDocument();
  });
});
  it("shows delete actions for registered models and stopped deployments", async () => {
    mocks.listDeployments.mockResolvedValue([deployment]);
    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Weld line (owner)"));

    expect(await screen.findByRole("button", { name: "Delete registered model Weld fault" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Deployments" }));
    expect(await screen.findByRole("button", { name: "Delete deployment line-a" })).toBeInTheDocument();
  });
