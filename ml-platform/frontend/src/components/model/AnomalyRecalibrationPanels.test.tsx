import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DeviceRecalibratePanel, LabelRecalibratePanel } from "./AnomalyRecalibrationPanels";

const mocks = vi.hoisted(() => ({
  labelRecalibrateVersion: vi.fn(),
  deriveSupervisedDataset: vi.fn(),
  recalibrateDeviceVersion: vi.fn(),
  addFleetShard: vi.fn(),
  fetchFleetOverview: vi.fn(),
}));

vi.mock("../../api/modelRegistry", () => mocks);

const labelResult = {
  version_id: "v2",
  registered_model_id: "m1",
  registered_model_name: "Weld anomaly",
  stats_artifact_id: "stats-1",
  old_threshold: 0.42,
  new_threshold: 0.55,
  loss: 0.12,
  fnr: 0.02,
  fpr: 0.01,
  gate: { unlocked: true, confirmed_count: 50, min_confirmed_required: 50, morphology_cluster_count: 2 },
  false_alarm_report: {
    sample_count: 30,
    clusters: [
      { cluster: 0, sample_count: 18, dense_features: [{ feature: "current", mean_z: -2.1 }] },
    ],
  },
  confirmed_count: 50,
  false_alarm_count: 30,
};

const derivedResult = {
  dataset_artifact_id: "ds-1",
  dataset_name: "回流派生集",
  rows: 120,
  positives: 50,
  negatives: 70,
  feature_columns: ["current", "voltage"],
  label_column: "feedback",
};

const deviceResult = (overrides: Record<string, unknown> = {}) => ({
  version_id: "v9",
  registered_model_id: "m1",
  registered_model_name: "Weld anomaly",
  stats_artifact_id: "stats-9",
  threshold_score: 0.48,
  unfit_for_fleet: false,
  fleet_fit: { compatible: true, fleet_fpr: 0.01, tolerance: 0.05, baseline_threshold: 0.45 },
  backtest: { synthetic_auc: 0.93, per_class_recall: { normal: 0.91 }, holdout_rows: 40 },
  calibration_rows: 200,
  ...overrides,
});

/** 面板内查询：antd 全局 message 提示与面板文案可能同词，按面板容器收敛断言范围。 */
const labelPanel = () => within(screen.getByTestId("label-recalibrate-panel"));
const devicePanel = () => within(screen.getByTestId("device-recalibrate-panel"));

describe("AnomalyRecalibrationPanels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.fetchFleetOverview.mockResolvedValue({
      deployment_id: "d1",
      condition_column: "STATION(工位号)",
      revision_id: "r1",
      revision_number: 2,
      shards: [],
      psi_per_shard: [],
    });
    mocks.labelRecalibrateVersion.mockResolvedValue(labelResult);
    mocks.deriveSupervisedDataset.mockResolvedValue(derivedResult);
    mocks.recalibrateDeviceVersion.mockResolvedValue(deviceResult());
    mocks.addFleetShard.mockResolvedValue({ revision_id: "r2", revision_number: 3, targets: [] });
  });

  it("recalibrates the label threshold and renders threshold, confirmed count and false-alarm report", async () => {
    render(
      <LabelRecalibratePanel
        versionId="v1"
        labeledArtifacts={[{ id: "a1", name: "回流标注集" }]}
      />,
    );

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "标注数据集" }));
    fireEvent.click(await screen.findByText("回流标注集"));
    fireEvent.click(screen.getByRole("button", { name: /M6 档 1 阈值重标定/ }));

    await waitFor(() => expect(mocks.labelRecalibrateVersion).toHaveBeenCalledWith("v1", {
      labeled_artifact_id: "a1",
    }));

    const summary = await labelPanel().findByText(/M6 重标定完成/);
    expect(summary.textContent).toContain("0.42");
    expect(summary.textContent).toContain("0.55");
    expect(summary.textContent).toContain("confirmed 50");
    expect(labelPanel().getByText("误报形态报表（样本 30）")).toBeInTheDocument();
    expect(labelPanel().getByText("current -2.1")).toBeInTheDocument();
    expect(labelPanel().getByRole("link", { name: /Weld anomaly/ })).toHaveAttribute("href", "/models");
  });

  it("derives the supervised dataset and shows the derived summary", async () => {
    render(
      <LabelRecalibratePanel
        versionId="v1"
        labeledArtifacts={[{ id: "a1", name: "回流标注集" }]}
        defaultArtifactId="a1"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "派生监督数据集" }));

    await waitFor(() => expect(mocks.deriveSupervisedDataset).toHaveBeenCalledWith("v1", {
      labeled_artifact_id: "a1",
    }));
    expect(await labelPanel().findByText(/派生监督数据集已生成/)).toHaveTextContent("50 正 / 70 负");
    expect(labelPanel().getByRole("link", { name: /回流派生集/ })).toHaveAttribute("href", "/data");
  });

  it("explains the M6 gate threshold when the backend answers 409", async () => {
    mocks.labelRecalibrateVersion.mockRejectedValue({
      response: {
        status: 409,
        data: {
          detail: {
            code: "M6_GATE_NOT_UNLOCKED",
            message: "档 1 前置门槛未达：confirmed 12/50、形态簇 1/2（§6.2 自动顺延）",
          },
        },
      },
    });

    render(
      <LabelRecalibratePanel
        versionId="v1"
        labeledArtifacts={[{ id: "a1", name: "回流标注集" }]}
        defaultArtifactId="a1"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /M6 档 1 阈值重标定/ }));

    const alert = await labelPanel().findByText(/confirmed_fault ≥50 未达/);
    expect(alert).toHaveTextContent("当前 12 条");
    expect(alert).toHaveTextContent("继续标注积累");
  });

  it("recalibrates a new device and reports the fleet fit verdict", async () => {
    render(
      <DeviceRecalibratePanel
        deploymentId="d1"
        sourceVersionId="v1"
        calibrationArtifact={{ id: "c1", name: "标定集" }}
        datasets={[{ id: "c2", name: "纯正常集" }]}
      />,
    );

    fireEvent.change(screen.getByLabelText("工况值（设备号/工位号）"), {
      target: { value: "ZZQX113" },
    });
    fireEvent.click(screen.getByRole("button", { name: "执行 M9 设备重标定" }));

    await waitFor(() => expect(mocks.recalibrateDeviceVersion).toHaveBeenCalledWith("v1", {
      calibration_artifact_id: "c1",
      condition_value: "ZZQX113",
    }));
    const summary = await devicePanel().findByText(/M9 设备重标定完成/);
    expect(summary).toHaveTextContent("机群兼容");
    expect(summary).toHaveTextContent("fleet_fpr 0.01");
    expect(summary).toHaveTextContent("标定样本 200 行");
  });

  it("refuses to mount an unfit migration version as a fleet shard", async () => {
    mocks.recalibrateDeviceVersion.mockResolvedValue(deviceResult({
      unfit_for_fleet: true,
      fleet_fit: { compatible: false, fleet_fpr: 0.2, tolerance: 0.05, baseline_threshold: 0.45 },
    }));

    render(
      <DeviceRecalibratePanel
        deploymentId="d1"
        sourceVersionId="v1"
        calibrationArtifact={{ id: "c1", name: "标定集" }}
        datasets={[]}
      />,
    );

    fireEvent.change(screen.getByLabelText("工况值（设备号/工位号）"), {
      target: { value: "ZZQX113" },
    });
    fireEvent.click(screen.getByRole("button", { name: "执行 M9 设备重标定" }));
    await devicePanel().findByText(/机群不适配（unfit）/);

    fireEvent.click(screen.getByRole("button", { name: /挂载为部署分片/ }));

    expect(await devicePanel().findByText(/不可挂载/)).toBeInTheDocument();
    expect(mocks.addFleetShard).not.toHaveBeenCalled();
  });
});
