import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DemoLoopDetailPage from "./DemoLoopDetailPage";

const demoLoopApi = vi.hoisted(() => ({
  fetchDemoLoops: vi.fn(),
  fetchDemoLoopStatusScoped: vi.fn(),
  fetchDemoLoopDeployments: vi.fn(),
  fetchDemoLoopDatasets: vi.fn(),
  fetchDemoLoopAnnotators: vi.fn(),
  predictDemoLoopRowScoped: vi.fn(),
  resetDemoLoopScoped: vi.fn(),
  updateDemoLoop: vi.fn(),
}));

// 模型注册写侧 API（M6 档 1 / 派生 / M9 设备重标定 + 分片挂载）
const modelRegistryApi = vi.hoisted(() => ({
  labelRecalibrateVersion: vi.fn(),
  deriveSupervisedDataset: vi.fn(),
  recalibrateDeviceVersion: vi.fn(),
  addFleetShard: vi.fn(),
  fetchFleetOverview: vi.fn(),
}));

vi.mock("../api/demoLoop", () => demoLoopApi);
vi.mock("../api/modelRegistry", () => modelRegistryApi);
vi.mock("../api/client", () => ({
  default: { request: vi.fn() },
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  formatApiError: vi.fn((_error: unknown, fallback: string) => fallback),
}));
vi.mock("../components/AppLayout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({ t: { nav: { demo_loop: "自动化闭环" }, demo_loop: {} } }),
}));

const CONFIG = {
  id: "cfg-1",
  project_id: "p1",
  name: "夜班告警闭环",
  deployment_id: "dep-1",
  error_classes: ["1"],
  preprocess_enabled: true,
  alert_threshold_rows: 2,
  require_review: false,
  review_annotator_ids: [],
  retrain_enabled: true,
  retrain_threshold_rows: 3,
  retrain_dataset_artifact_id: "ds-1",
  retrain_dataset_artifact_ids: ["ds-1"],
  retrain_target_column: "fault",
  retrain_max_trials: 5,
  retrain_dataset: null,
  deployment: { id: "dep-1", name: "11", desired_state: "running", observed_state: "running" },
  current_model: null,
  swapped_model_version_id: null,
  error_count: 3,
  alert_count: 1,
  total_count: 7,
  retrain_status: "completed",
  created_at: null,
  updated_at: null,
};

const STATUS = {
  config_id: "cfg-1",
  error_count: 3,
  alert_count: 1,
  total_count: 7,
  retrain_status: "completed",
  retrain_job_id: "job-9",
  review_task_id: null,
  swapped_model_version_id: null,
  error_artifact: { id: "art-1", name: "夜班告警闭环-报错数据", row_count: 3 },
  events: [],
};

// 有模型版本 + 有部署的闭环（机群场景）：M6 / M9 入口的渲染前提
const FLEET_STATUS = {
  ...STATUS,
  swapped_model_version_id: "ver-1",
  deployment_id: "dep-1",
};

const M6_RESULT = {
  version_id: "ver-m6",
  registered_model_id: "rm-1",
  registered_model_name: "焊点异常检测-M6",
  stats_artifact_id: "stats-m6",
  old_threshold: 0.42,
  new_threshold: 0.55,
  loss: 0.13,
  fnr: 0.02,
  fpr: 0.01,
  gate: { unlocked: true, confirmed_count: 60, min_confirmed_required: 50, morphology_cluster_count: 2 },
  false_alarm_report: {
    clusters: [
      { cluster: 0, sample_count: 12, dense_features: [{ feature: "weld_current", mean_z: 3.21, mean_raw: 412.5 }] },
      { cluster: 1, sample_count: 5, dense_features: [{ feature: "squeeze_time", mean_z: -2.4, mean_raw: 0.18 }] },
    ],
    sample_count: 17,
  },
  confirmed_count: 60,
  false_alarm_count: 17,
};

const DERIVED_RESULT = {
  dataset_artifact_id: "art-derived",
  dataset_name: "回流标签监督数据集",
  rows: 90,
  positives: 60,
  negatives: 30,
  feature_columns: ["weld_current", "squeeze_time"],
  label_column: "feedback",
};

const M9_COMPATIBLE = {
  version_id: "ver-m9",
  registered_model_id: "rm-device",
  registered_model_name: "焊点异常检测-device-ZZQX113",
  stats_artifact_id: "stats-m9",
  threshold_score: 0.61,
  unfit_for_fleet: false,
  fleet_fit: { compatible: true, fleet_fpr: 0.0125, tolerance: 0.015, baseline_threshold: 0.55 },
  backtest: { synthetic_auc: 0.93, per_class_recall: { uniform_outlier: 0.9 }, holdout_rows: 40 },
  calibration_rows: 200,
};

const M9_UNFIT = {
  ...M9_COMPATIBLE,
  version_id: "ver-m9-unfit",
  unfit_for_fleet: true,
  fleet_fit: { compatible: false, fleet_fpr: 1.0, tolerance: 0.015, baseline_threshold: 0.55 },
};

const FLEET_SHARD_RESULT = {
  revision_id: "rev-2",
  revision_number: 2,
  targets: [
    { model_version_id: "ver-base", condition_value: null, weight_bps: 5000 },
    { model_version_id: "ver-m9", condition_value: "ZZQX113", weight_bps: 5000 },
  ],
};

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={["/demo-loop/cfg-1?project=p1"]}>
      <Routes>
        <Route path="/demo-loop/:loopId" element={<DemoLoopDetailPage />} />
        <Route path="/demo-loop" element={<div>LIST</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DemoLoopDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    demoLoopApi.fetchDemoLoops.mockResolvedValue({ items: [CONFIG] });
    demoLoopApi.fetchDemoLoopStatusScoped.mockResolvedValue(STATUS);
    demoLoopApi.fetchDemoLoopDeployments.mockResolvedValue({ items: [] });
    demoLoopApi.fetchDemoLoopDatasets.mockResolvedValue({ items: [] });
    demoLoopApi.fetchDemoLoopAnnotators.mockResolvedValue({ items: [] });
    modelRegistryApi.fetchFleetOverview.mockResolvedValue({
      deployment_id: "dep-1",
      condition_column: "device_id",
      revision_id: "rev-1",
      revision_number: 1,
      shards: [],
      psi_per_shard: null,
    });
    modelRegistryApi.labelRecalibrateVersion.mockResolvedValue(M6_RESULT);
    modelRegistryApi.deriveSupervisedDataset.mockResolvedValue(DERIVED_RESULT);
    modelRegistryApi.recalibrateDeviceVersion.mockResolvedValue(M9_COMPATIBLE);
    modelRegistryApi.addFleetShard.mockResolvedValue(FLEET_SHARD_RESULT);
  });

  it("loads the scoped loop and renders inference + status panels", async () => {
    renderDetail();
    await waitFor(() => expect(demoLoopApi.fetchDemoLoopStatusScoped).toHaveBeenCalledWith("p1", "cfg-1"));
    expect(screen.getAllByText("夜班告警闭环").length).toBeGreaterThan(0);
    expect(screen.getByText(/逐行推理调用/)).toBeInTheDocument();
    expect(screen.getByText(/闭环状态/)).toBeInTheDocument();
    expect(screen.getByText("返回任务列表")).toBeInTheDocument();
    expect(screen.getByText(/夜班告警闭环-报错数据/)).toBeInTheDocument();
    // 已推理/回流行数来自 scoped status
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows the retrain task link from scoped status", async () => {
    renderDetail();
    await waitFor(() => expect(screen.getByText(/查看自动建模任务/)).toBeInTheDocument());
    expect(screen.getByText(/查看自动建模任务/).closest("a")).toHaveAttribute("href", "/automl/task/job-9");
  });

  it("renders back-navigation to the list page", async () => {
    renderDetail();
    await waitFor(() => expect(screen.getByText("返回任务列表")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /编辑配置/ })).toBeInTheDocument();
  });

  it("M9 入口渲染并以「标定数据集 + 工况值」调用 recalibrate-device", async () => {
    demoLoopApi.fetchDemoLoopStatusScoped.mockResolvedValue(FLEET_STATUS);
    renderDetail();
    const conditionInput = await screen.findByPlaceholderText("工况值（设备号/工位号）");
    fireEvent.change(conditionInput, { target: { value: "ZZQX113" } });
    fireEvent.click(screen.getByRole("button", { name: "执行 M9 设备重标定" }));
    await waitFor(() => expect(modelRegistryApi.recalibrateDeviceVersion).toHaveBeenCalledWith("ver-1", {
      calibration_artifact_id: "art-1",
      condition_value: "ZZQX113",
    }));
    // 结果：兼容判定 + fleet_fpr + 新版本 id
    expect((await screen.findAllByText(/机群兼容/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/ver-m9/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/fleet_fpr 0.0125/).length).toBeGreaterThan(0);
  });

  it("M9 挂载调用 fleet-shards（工况值 + 工况列 + 行数比例）", async () => {
    demoLoopApi.fetchDemoLoopStatusScoped.mockResolvedValue(FLEET_STATUS);
    renderDetail();
    const conditionInput = await screen.findByPlaceholderText("工况值（设备号/工位号）");
    fireEvent.change(conditionInput, { target: { value: "ZZQX113" } });
    fireEvent.click(screen.getByRole("button", { name: "执行 M9 设备重标定" }));
    await waitFor(() => expect(modelRegistryApi.recalibrateDeviceVersion).toHaveBeenCalled());
    const rowsInput = await screen.findByPlaceholderText("新分片行数");
    fireEvent.change(rowsInput, { target: { value: "200" } });
    const totalRowsInput = screen.getByPlaceholderText("总分片行数");
    fireEvent.change(totalRowsInput, { target: { value: "1000" } });
    fireEvent.click(screen.getByRole("button", { name: "挂载为部署分片" }));
    await waitFor(() => expect(modelRegistryApi.addFleetShard).toHaveBeenCalledWith("dep-1", {
      model_version_id: "ver-m9",
      condition_value: "ZZQX113",
      condition_column: "device_id",
      rows: 200,
      total_rows: 1000,
    }));
  });

  it("M9 unfit 结果以告警呈现且拒绝挂载（不静默调用 fleet-shards）", async () => {
    demoLoopApi.fetchDemoLoopStatusScoped.mockResolvedValue(FLEET_STATUS);
    modelRegistryApi.recalibrateDeviceVersion.mockResolvedValue(M9_UNFIT);
    renderDetail();
    const conditionInput = await screen.findByPlaceholderText("工况值（设备号/工位号）");
    fireEvent.change(conditionInput, { target: { value: "DPQQ02" } });
    fireEvent.click(screen.getByRole("button", { name: "执行 M9 设备重标定" }));
    await waitFor(() => expect(modelRegistryApi.recalibrateDeviceVersion).toHaveBeenCalled());
    // unfit → 告警（不硬迁）
    expect((await screen.findAllByText(/机群不适配/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/不硬迁/).length).toBeGreaterThan(0);
    // 挂载被界面拒绝：不调用 fleet-shards，并给出明确原因
    fireEvent.click(screen.getByRole("button", { name: /挂载为部署分片/ }));
    await waitFor(() => expect(screen.getAllByText(/不可挂载/).length).toBeGreaterThan(0));
    expect(modelRegistryApi.addFleetShard).not.toHaveBeenCalled();
  });

  it("M6 结果展示误报形态报表（形态簇 + 密集特征 mean_z）与派生版本链接", async () => {
    demoLoopApi.fetchDemoLoopStatusScoped.mockResolvedValue(FLEET_STATUS);
    renderDetail();
    fireEvent.click(await screen.findByRole("button", { name: /M6 档 1 阈值重标定/ }));
    await waitFor(() => expect(modelRegistryApi.labelRecalibrateVersion).toHaveBeenCalledWith("ver-1", {
      labeled_artifact_id: "art-1",
    }));
    // 误报形态报表：形态簇样本数 + 密集特征（feature + mean_z）
    expect(await screen.findByText("误报形态报表（样本 17）")).toBeInTheDocument();
    expect(screen.getByText("weld_current 3.21")).toBeInTheDocument();
    expect(screen.getByText("squeeze_time -2.4")).toBeInTheDocument();
    // 派生版本链接（数据管理页 artifact 链接）
    fireEvent.click(screen.getByRole("button", { name: "派生监督数据集" }));
    await waitFor(() => expect(modelRegistryApi.deriveSupervisedDataset).toHaveBeenCalled());
    const derivedLink = await screen.findByText("回流标签监督数据集（artifact art-derived）");
    expect(derivedLink.closest("a")).toHaveAttribute("href", "/data?projectId=p1");
  });
});
