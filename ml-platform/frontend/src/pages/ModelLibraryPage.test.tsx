import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ModelLibraryPage from "./ModelLibraryPage";

const mocks = vi.hoisted(() => ({
  listRegisteredModels: vi.fn(), createRegisteredModel: vi.fn(), listModelVersions: vi.fn(),
  registerPlatformVersion: vi.fn(), approveModelVersion: vi.fn(), rejectModelVersion: vi.fn(),
  listDeployments: vi.fn(), createDeployment: vi.fn(), startDeployment: vi.fn(),
  stopDeployment: vi.fn(), predictDeployment: vi.fn(),
  listRollouts: vi.fn(), createRollout: vi.fn(), pauseRollout: vi.fn(), resumeRollout: vi.fn(), rollbackRollout: vi.fn(),
  listInferenceApiKeys: vi.fn(), createInferenceApiKey: vi.fn(), rotateInferenceApiKey: vi.fn(), revokeInferenceApiKey: vi.fn(),
  listInferenceMetrics: vi.fn(), listInferenceMetricWindow: vi.fn(), listInferenceRequestLogs: vi.fn(), getModelCard: vi.fn(),
  updateModelCardGuidance: vi.fn(), exportModelCard: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/modelRegistry", () => mocks);
vi.mock("../api/client", () => ({
  default: { get: vi.fn().mockResolvedValue({ data: { items: [
    { id: "p1", name: "Weld line", project_role: "owner" },
    { id: "p2", name: "Read only", project_role: "viewer" },
    { id: "p3", name: "Operate only", project_role: "operator" },
  ] } }) },
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("../i18n", () => ({ useI18n: () => ({ t: {
  common: { create: "Create", cancel: "Cancel", refresh: "Refresh", close: "Close" },
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
    production: {
      releaseOperations: "Release operations", release: "release", releases: "Releases", releaseState: "Release state", targetWeights: "Target weights",
      createRollout: "Create rollout", strategy: "Strategy", targetVersion: "Target version", targetWeight: "Target weight",
      pause: "Pause", resume: "Resume", rollback: "Rollback", pauseConfirmation: "Pause this release?", resumeConfirmation: "Resume this release?", confirmPause: "Confirm pause", confirmResume: "Confirm resume", rollbackConfirmation: "Rollback this release?", confirmRollback: "Confirm rollback",
      emptyRollouts: "No releases", apiKeys: "API keys", emptyApiKeys: "No API keys", createApiKey: "Create API key",
      rotateApiKey: "Rotate API key", revokeApiKey: "Revoke API key", keyCreated: "API key created", keyPlaintext: "API key plaintext",
      closeCreatedKey: "Close created key", metrics: "Metrics", throughput: "Throughput", errorRate: "Error rate", latency: "Latency",
      emptyMetrics: "No metrics", requestLogs: "Request logs", emptyRequestLogs: "No request logs", modelCard: "Model card",
      openModelCard: "Open model card", operationalGuidance: "Operational guidance", saveGuidance: "Save guidance", exportModelCard: "Export model card", failedRollout: "Failed rollout", emptyModelCard: "No model card", guidanceUpdated: "Guidance updated", cardExported: "Model card exported",
      immediate: "Immediate", canary: "Canary", rolling: "Rolling", keyPrefix: "Prefix", keyStatus: "Status", revoked: "Revoked", active: "Active", expired: "Expired", logStatus: "Status", logDuration: "Duration", logBatch: "Batch size", logError: "Error code", logOccurred: "Occurred at",
      statusLabels: { pending: "Awaiting rollout", preloading: "Preloading", progressing: "Progressing", paused: "Paused", completed: "Completed", failed: "Release failed", rolled_back: "Rolled back", success: "Success", error: "Error", limited: "Rate limited", revoked: "Revoked", active: "Active" },
      last24Hours: "Last 24 hours",
    },
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

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
    mocks.listRollouts.mockResolvedValue({ items: [], total: 0 });
    mocks.createRollout.mockResolvedValue({ id: "r1", state: "pending", lock_version: 1, targets: [] });
    mocks.pauseRollout.mockResolvedValue({ id: "r1", state: "paused", lock_version: 2, targets: [] });
    mocks.resumeRollout.mockResolvedValue({ id: "r1", state: "progressing", lock_version: 3, targets: [] });
    mocks.rollbackRollout.mockResolvedValue({ id: "r1", state: "rolled_back", lock_version: 8, targets: [] });
    mocks.listInferenceApiKeys.mockResolvedValue({ items: [], total: 0 });
    mocks.createInferenceApiKey.mockResolvedValue({ id: "k2", prefix: "pk_live_123", plaintext: "once-only" });
    mocks.rotateInferenceApiKey.mockResolvedValue({ id: "k1", prefix: "pk_live_456", plaintext: "rotated-once" });
    mocks.revokeInferenceApiKey.mockResolvedValue({ id: "k1", revoked_at: "2026-07-20T00:00:00Z" });
    mocks.listInferenceMetrics.mockResolvedValue({ items: [], summary: { request_count: 0, error_count: 0, p95_latency_ms: 0 } });
    mocks.listInferenceMetricWindow.mockResolvedValue({ items: [], summary: { request_count: 0, error_count: 0, p95_latency_ms: 0 }, page: 1, page_size: 200 });
    mocks.listInferenceRequestLogs.mockResolvedValue({ items: [], page: 1, page_size: 100 });
    mocks.getModelCard.mockResolvedValue({ id: "card-1", model_version_id: "v1", operational_guidance: "Watch drift.", guidance_revision: 1, approval_status: "approved", release_status: "released" });
    mocks.updateModelCardGuidance.mockResolvedValue({ id: "card-1", operational_guidance: "Use a reviewed threshold.", guidance_revision: 2 });
    mocks.exportModelCard.mockResolvedValue({ id: "card-1", format: "markdown" });
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

  it("confirms rollback, clears a one-time API key, and saves model-card guidance", async () => {
    mocks.listDeployments.mockResolvedValue([deployment]);
    mocks.listModelVersions.mockResolvedValue([version]);
    mocks.pauseRollout.mockResolvedValue({ id: "r0", state: "paused", lock_version: 6, current_step: 5000, step_schedule: [0, 5000, 10000], targets: [] });
    mocks.resumeRollout.mockResolvedValue({ id: "r0", state: "progressing", lock_version: 7, current_step: 5000, step_schedule: [0, 5000, 10000], targets: [] });
    mocks.listInferenceRequestLogs.mockResolvedValue({
      items: Array.from({ length: 2 }, (_, index) => ({ id: `log-${index}`, status: "success", duration_ms: 4, batch_size: 1, error_code: null, occurred_at: "2026-07-20T00:00:00Z" })),
      page: 1,
      page_size: 2,
    });
    mocks.listRollouts.mockResolvedValue({ items: [
      { id: "r0", state: "progressing", lock_version: 5, current_step: 5000, step_schedule: [0, 5000, 10000], targets: [] },
      { id: "r1", state: "completed", lock_version: 7, targets: [{ model_version_id: "v1", weight_bps: 10000 }] },
      { id: "r2", state: "failed", lock_version: 4, last_error_code: "ROLLOUT_THRESHOLD_EXCEEDED", targets: [] },
    ], total: 3 });
    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Weld line (owner)"));
    fireEvent.click(screen.getByRole("tab", { name: "Deployments" }));
    fireEvent.click(await screen.findByRole("button", { name: "Release operations line-a" }));

    expect(await screen.findByText("ROLLOUT_THRESHOLD_EXCEEDED")).toBeInTheDocument();
    expect(screen.getByText("No metrics")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Next Page"));
    await waitFor(() => expect(mocks.listInferenceRequestLogs).toHaveBeenLastCalledWith("d1", expect.objectContaining({ page: 2 })));
    fireEvent.click(screen.getByRole("button", { name: "Pause release r0" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm pause" }));
    await waitFor(() => expect(mocks.pauseRollout).toHaveBeenCalledWith("d1", "r0", 5));
    fireEvent.click(await screen.findByRole("button", { name: "Resume release r0" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm resume" }));
    await waitFor(() => expect(mocks.resumeRollout).toHaveBeenCalledWith("d1", "r0", 6));
    fireEvent.click(screen.getByRole("button", { name: "Rollback release r1" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm rollback" }));
    await waitFor(() => expect(mocks.rollbackRollout).toHaveBeenCalledWith("d1", "r1", 7));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Confirm rollback" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Rollback release r2" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm rollback" }));
    await waitFor(() => expect(mocks.rollbackRollout).toHaveBeenLastCalledWith("d1", "r2", 4));

    fireEvent.click(screen.getByRole("button", { name: "Create API key" }));
    expect(await screen.findByDisplayValue("once-only")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close created key" }));
    await waitFor(() => expect(screen.queryByDisplayValue("once-only")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Open model card" }));
    const guidance = await screen.findByLabelText("Operational guidance");
    fireEvent.change(guidance, { target: { value: "Use a reviewed threshold." } });
    fireEvent.click(screen.getByRole("button", { name: "Save guidance" }));
    await waitFor(() => expect(mocks.updateModelCardGuidance).toHaveBeenCalledWith("card-1", "Use a reviewed threshold."));

    const originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
    const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
    const createObjectURL = vi.fn(() => "blob:model-card");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    fireEvent.click(screen.getByRole("button", { name: "Export model card" }));
    await waitFor(() => expect(mocks.exportModelCard).toHaveBeenCalledWith("card-1"));
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:model-card");
    click.mockRestore();
    if (originalCreateObjectURL) Object.defineProperty(URL, "createObjectURL", originalCreateObjectURL);
    else delete (URL as unknown as Record<string, unknown>).createObjectURL;
    if (originalRevokeObjectURL) Object.defineProperty(URL, "revokeObjectURL", originalRevokeObjectURL);
    else delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
  }, 15_000);

  it("keeps viewer rollout operations read-only while showing failures and empty metrics", async () => {
    mocks.listDeployments.mockResolvedValue([deployment]);
    mocks.listRollouts.mockResolvedValue({ items: [{ id: "r2", state: "failed", lock_version: 4, last_error_code: "ROLLOUT_PRELOAD_FAILED", targets: [] }], total: 1 });
    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Read only (viewer)"));
    fireEvent.click(screen.getByRole("tab", { name: "Deployments" }));
    fireEvent.click(await screen.findByRole("button", { name: "Release operations line-a" }));

    expect(await screen.findByText("ROLLOUT_PRELOAD_FAILED")).toBeInTheDocument();
    expect(screen.getByText("No metrics")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create rollout" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create API key" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rollback release r2" })).not.toBeInTheDocument();
  }, 15_000);

  it("lets an operator control an existing rollout without managing releases or API keys", async () => {
    mocks.listDeployments.mockResolvedValue([deployment]);
    mocks.listRollouts.mockResolvedValue({ items: [{ id: "r1", state: "progressing", lock_version: 4, targets: [] }], total: 1 });
    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Operate only (operator)"));
    fireEvent.click(screen.getByRole("tab", { name: "Deployments" }));
    fireEvent.click(await screen.findByRole("button", { name: "Release operations line-a" }));

    expect(await screen.findByRole("button", { name: "Pause release r1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create rollout" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create API key" })).not.toBeInTheDocument();
    expect(mocks.listInferenceApiKeys).not.toHaveBeenCalled();
  }, 15_000);

  it("ignores a created API key after switching to another deployment", async () => {
    const created = deferred<{ id: string; prefix: string; plaintext: string }>();
    mocks.listDeployments.mockResolvedValue([
      deployment,
      { ...deployment, id: "d2", name: "line-b", model_version_id: "v2" },
    ]);
    mocks.createInferenceApiKey.mockReturnValue(created.promise);
    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Weld line (owner)"));
    fireEvent.click(screen.getByRole("tab", { name: "Deployments" }));
    fireEvent.click(await screen.findByRole("button", { name: "Release operations line-a" }));
    fireEvent.click(await screen.findByRole("button", { name: "Create API key" }));
    fireEvent.click(screen.getByRole("button", { name: "Release operations line-b" }));
    await waitFor(() => expect(mocks.listRollouts).toHaveBeenCalledWith("d2"));

    await act(async () => {
      created.resolve({ id: "k-prior", prefix: "pk_live_prior", plaintext: "prior-once-only" });
      await Promise.resolve();
    });

    expect(screen.queryByDisplayValue("prior-once-only")).not.toBeInTheDocument();
    expect(screen.queryByText("pk_live_prior")).not.toBeInTheDocument();
  }, 15_000);

  it("does not reveal a created API key after closing release operations", async () => {
    const created = deferred<{ id: string; prefix: string; plaintext: string }>();
    mocks.listDeployments.mockResolvedValue([deployment]);
    mocks.createInferenceApiKey.mockReturnValue(created.promise);
    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Weld line (owner)"));
    fireEvent.click(screen.getByRole("tab", { name: "Deployments" }));
    fireEvent.click(await screen.findByRole("button", { name: "Release operations line-a" }));
    fireEvent.click(await screen.findByRole("button", { name: "Create API key" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await act(async () => {
      created.resolve({ id: "k-closed", prefix: "pk_live_closed", plaintext: "closed-once-only" });
      await Promise.resolve();
    });

    expect(screen.queryByDisplayValue("closed-once-only")).not.toBeInTheDocument();
  }, 15_000);

  it("marks expired API keys and disables rotation", async () => {
    mocks.listDeployments.mockResolvedValue([deployment]);
    mocks.listInferenceApiKeys.mockResolvedValue({
      items: [{ id: "k-expired", prefix: "pk_live_expired", scopes: ["inference.predict"], expires_at: "2000-01-01T00:00:00Z", revoked_at: null }],
      total: 1,
    });
    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Weld line (owner)"));
    fireEvent.click(screen.getByRole("tab", { name: "Deployments" }));
    fireEvent.click(await screen.findByRole("button", { name: "Release operations line-a" }));

    expect(await screen.findByText("Expired")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rotate API key pk_live_expired" })).toBeDisabled();
  }, 15_000);

  it("keeps the latest release drawer data when an earlier load finishes late", async () => {
    const staleRollouts = deferred<{ items: Array<Record<string, unknown>>; total: number }>();
    mocks.listDeployments.mockResolvedValue([
      deployment,
      { ...deployment, id: "d2", name: "line-b", model_version_id: "v2" },
    ]);
    mocks.listRollouts.mockImplementation((deploymentId: string) => (
      deploymentId === "d1"
        ? staleRollouts.promise
        : Promise.resolve({
          items: [{ id: "r-current", state: "failed", lock_version: 1, last_error_code: "CURRENT_RELEASE", targets: [] }],
          total: 1,
        })
    ));

    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Weld line (owner)"));
    fireEvent.click(screen.getByRole("tab", { name: "Deployments" }));
    fireEvent.click(await screen.findByRole("button", { name: "Release operations line-a" }));
    await waitFor(() => expect(mocks.listRollouts).toHaveBeenCalledWith("d1"));
    fireEvent.click(screen.getByRole("button", { name: "Release operations line-b" }));
    expect(await screen.findByText("CURRENT_RELEASE")).toBeInTheDocument();

    staleRollouts.resolve({
      items: [{ id: "r-stale", state: "failed", lock_version: 1, last_error_code: "STALE_RELEASE", targets: [] }],
      total: 1,
    });

    await waitFor(() => expect(screen.queryByText("STALE_RELEASE")).not.toBeInTheDocument());
    expect(screen.getByText("CURRENT_RELEASE")).toBeInTheDocument();
  }, 15_000);

  it("refreshes API-key metadata after a rotation returns a distinct key id", async () => {
    mocks.listDeployments.mockResolvedValue([deployment]);
    mocks.listInferenceApiKeys
      .mockResolvedValueOnce({
        items: [{ id: "k1", prefix: "pk_live_old", scopes: ["inference.predict"], revoked_at: null }],
        total: 1,
      })
      .mockResolvedValueOnce({
        items: [
          { id: "k2", prefix: "pk_live_new", scopes: ["inference.predict"], revoked_at: null },
          { id: "k1", prefix: "pk_live_old", scopes: ["inference.predict"], revoked_at: "2026-07-20T00:00:00Z" },
        ],
        total: 2,
      });
    mocks.rotateInferenceApiKey.mockResolvedValue({ id: "k2", prefix: "pk_live_new", plaintext: "rotated-once" });

    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Weld line (owner)"));
    fireEvent.click(screen.getByRole("tab", { name: "Deployments" }));
    fireEvent.click(await screen.findByRole("button", { name: "Release operations line-a" }));
    fireEvent.click(await screen.findByRole("button", { name: "Rotate API key pk_live_old" }));

    await waitFor(() => expect(mocks.rotateInferenceApiKey).toHaveBeenCalledWith("k1"));
    await waitFor(() => expect(mocks.listInferenceApiKeys).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("pk_live_new")).toBeInTheDocument();
    expect(screen.getByText("Revoked")).toBeInTheDocument();
  }, 15_000);

  it("does not navigate to an empty inferred log page", async () => {
    mocks.listDeployments.mockResolvedValue([deployment]);
    mocks.listInferenceRequestLogs
      .mockResolvedValueOnce({
        items: Array.from({ length: 100 }, (_, index) => ({ id: `log-${index}`, status: "success", duration_ms: 4, batch_size: 1, error_code: index === 0 ? "FIRST_PAGE_LOG" : null, occurred_at: "2026-07-20T00:00:00Z" })),
        page: 1,
        page_size: 100,
      })
      .mockResolvedValueOnce({ items: [], page: 2, page_size: 100 });

    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Weld line (owner)"));
    fireEvent.click(screen.getByRole("tab", { name: "Deployments" }));
    fireEvent.click(await screen.findByRole("button", { name: "Release operations line-a" }));
    expect(await screen.findByText("FIRST_PAGE_LOG")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Next Page"));

    await waitFor(() => expect(mocks.listInferenceRequestLogs).toHaveBeenLastCalledWith("d1", expect.objectContaining({ page: 2 })));
    expect(screen.getByText("FIRST_PAGE_LOG")).toBeInTheDocument();
    expect(screen.queryByText("No request logs")).not.toBeInTheDocument();
  }, 15_000);

  it("uses production labels for rollout and request-log states and labels the 24-hour metric window", async () => {
    mocks.listDeployments.mockResolvedValue([deployment]);
    mocks.listRollouts.mockResolvedValue({ items: [{ id: "r1", state: "pending", lock_version: 2, targets: [] }], total: 1 });
    mocks.listInferenceMetricWindow.mockResolvedValue({
      items: [{ bucket_start: "2026-07-20T00:00:00Z", request_count: 2, error_count: 0, latency_buckets: { "5": 2 } }],
      summary: { request_count: 2, error_count: 0, p95_latency_ms: 5 },
      page: 1,
      page_size: 200,
    });
    mocks.listInferenceRequestLogs.mockResolvedValue({
      items: [{ id: "log-1", status: "success", duration_ms: 4, batch_size: 1, error_code: null, occurred_at: "2026-07-20T00:00:00Z" }],
      page: 1,
      page_size: 100,
    });

    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Weld line (owner)"));
    fireEvent.click(screen.getByRole("tab", { name: "Deployments" }));
    fireEvent.click(await screen.findByRole("button", { name: "Release operations line-a" }));

    expect(await screen.findByText("Awaiting rollout")).toBeInTheDocument();
    expect(screen.getByText("Success")).toBeInTheDocument();
    expect(screen.getByText("Last 24 hours")).toBeInTheDocument();
  }, 15_000);

  it("keeps model approval labels separate from rollout labels", async () => {
    mocks.listModelVersions.mockResolvedValue([version]);
    render(<AntApp><ModelLibraryPage /></AntApp>);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Weld line (owner)"));
    fireEvent.click(await screen.findByRole("button", { name: "Versions Weld fault" }));

    expect(await screen.findByText("Pending")).toBeInTheDocument();
    expect(screen.queryByText("Awaiting rollout")).not.toBeInTheDocument();
  }, 15_000);
});
