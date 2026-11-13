import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import FleetShardPanel from "./FleetShardPanel";

const mocks = vi.hoisted(() => ({
  fetchFleetOverview: vi.fn(),
}));

vi.mock("../../api/modelRegistry", () => mocks);

const shard = (overrides: Record<string, unknown> = {}) => ({
  condition_value: "ZZQX113",
  model_version_id: "v1",
  version_number: 1,
  weight_bps: 6000,
  threshold_score: 0.5,
  fleet_compatible: true,
  recalibration: false,
  backtest: null,
  running: null,
  ...overrides,
});

describe("FleetShardPanel", () => {
  it("renders the per-device running alarm rate column (M10 per-device fpr)", async () => {
    mocks.fetchFleetOverview.mockResolvedValue({
      deployment_id: "d1",
      condition_column: "STATION(工位号)",
      revision_id: "r1",
      revision_number: 2,
      shards: [
        shard({ running: { rows: 1000, alerts: 12, alert_rate: 0.012 } }),
        shard({
          condition_value: "DPQQ02",
          model_version_id: "v2",
          running: { rows: 500, alerts: 40, alert_rate: 0.08 },
        }),
      ],
      psi_per_shard: [],
    });
    render(<FleetShardPanel deploymentId="d1" />);
    await waitFor(() => expect(screen.getByText("运行期报警率")).toBeTruthy());
    expect(screen.getByText("1.20%")).toBeTruthy();
    expect(screen.getByText("8.00%")).toBeTruthy();
  });

  it("renders a dash when a shard has no running reflow data", async () => {
    mocks.fetchFleetOverview.mockResolvedValue({
      deployment_id: "d1",
      condition_column: "STATION(工位号)",
      revision_id: "r1",
      revision_number: 2,
      shards: [shard({ running: null })],
      psi_per_shard: [],
    });
    render(<FleetShardPanel deploymentId="d1" />);
    await waitFor(() => expect(screen.getByText("运行期报警率")).toBeTruthy());
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("stays hidden for ordinary (non condition-sharded) deployments", async () => {
    mocks.fetchFleetOverview.mockResolvedValue({
      deployment_id: "d2",
      condition_column: null,
      revision_id: "r1",
      revision_number: 1,
      shards: [shard()],
      psi_per_shard: null,
    });
    render(<FleetShardPanel deploymentId="d2" />);
    await waitFor(() => expect(mocks.fetchFleetOverview).toHaveBeenCalledWith("d2"));
    expect(screen.queryByText(/机群分片概览/)).toBeNull();
  });
});
