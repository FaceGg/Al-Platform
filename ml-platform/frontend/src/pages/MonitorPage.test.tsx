import { render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import MonitorPage from "./MonitorPage";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get } }));
vi.mock("../i18n", () => ({ useI18n: () => ({ t: {
  monitor: {
    title: "Monitor", refresh: "Refresh", cpu: "CPU", memory: "Memory", disk: "Disk", gpu: "GPU",
    used: "Used", total: "Total", usage: "Usage", temperature: "Temp", no_gpu: "No GPU detected",
    net: "Network", diskio: "Disk I/O", load: "Load", down: "Down", up: "Up",
    readOp: "Read", writeOp: "Write", uptime: "Uptime", updated: "Updated",
  },
} }) }));
vi.mock("react-router-dom", async () => ({
  ...(await vi.importActual<typeof import("react-router-dom")>("react-router-dom")),
}));

function gpu(index: number) {
  return { gpu_util: 40 + index, memory_used_mb: 1024 * (index + 1), memory_total_mb: 8192, temperature_c: 50 + index };
}

function mockBackend(gpus: any[]) {
  get.mockImplementation((url: string) => {
    if (url === "/monitor/current") {
      return Promise.resolve({ data: {
        timestamp: "2026-10-08T02:00:10+00:00",
        cpu: { percent: 12 },
        memory: { percent: 30 },
        disk: { percent: 40 },
        gpu: gpus,
        load: { load1: 0.5, load5: 0.4, load15: 0.3, cpu_cores: 8 },
        net: { rx_bytes: 2_600_000, tx_bytes: 1_300_000 },
        disk_io: { read_bytes: 11_000_000, write_bytes: 5_500_000 },
        uptime_seconds: 90061,
      } });
    }
    if (url === "/monitor/history") {
      return Promise.resolve({ data: [
        { timestamp: "2026-10-08T02:00:00+00:00", cpu: { percent: 5 }, memory: { percent: 29 }, disk: { percent: 39 },
          gpu: gpus.map((g) => ({ gpu_util: g.gpu_util - 10 })), load: { load1: 0.2, cpu_cores: 8 },
          net: { rx_bytes: 1_000_000, tx_bytes: 500_000 }, disk_io: { read_bytes: 5_000_000, write_bytes: 2_500_000 },
          uptime_seconds: 90000 },
        { timestamp: "2026-10-08T02:00:05+00:00", cpu: { percent: 8 }, memory: { percent: 30 }, disk: { percent: 40 },
          gpu: gpus.map((g) => ({ gpu_util: g.gpu_util })), load: { load1: 0.4, cpu_cores: 8 },
          net: { rx_bytes: 2_000_000, tx_bytes: 1_000_000 }, disk_io: { read_bytes: 10_000_000, write_bytes: 5_000_000 },
          uptime_seconds: 90005 },
      ] });
    }
    return Promise.reject(new Error(`Unexpected URL: ${url}`));
  });
}

describe("MonitorPage", () => {
  beforeEach(() => {
    mockBackend([]);
  });

  it("shows resource metrics without the removed quality warning panel", async () => {
    render(<MemoryRouter><AntApp><MonitorPage /></AntApp></MemoryRouter>);
    expect(await screen.findByText("CPU")).toBeInTheDocument();
    expect(screen.queryByText("点焊质量预警")).not.toBeInTheDocument();
  });

  it("backfills trend lines and I/O rates from the backend history buffer", async () => {
    render(<MemoryRouter><AntApp><MonitorPage /></AntApp></MemoryRouter>);
    await screen.findByText("CPU");
    expect(get).toHaveBeenCalledWith("/monitor/history", { params: { limit: 60 } });
    // Live rate: 600 KB received over the 5 s since the history tail
    // = 120,000 B/s = 117.2 KB/s.
    expect(await screen.findByText(/117\.2 KB\/s/)).toBeInTheDocument();
  });

  it("renders one card per GPU when multiple GPUs are detected", async () => {
    mockBackend([gpu(0), gpu(1)]);
    render(<MemoryRouter><AntApp><MonitorPage /></AntApp></MemoryRouter>);
    expect(await screen.findByText("GPU 1")).toBeInTheDocument();
    expect(screen.getByText("GPU 2")).toBeInTheDocument();
    expect(screen.getByText("Temp: 51°C")).toBeInTheDocument();
  });

  it("notes when no GPU is detected", async () => {
    render(<MemoryRouter><AntApp><MonitorPage /></AntApp></MemoryRouter>);
    expect(await screen.findByText("No GPU detected")).toBeInTheDocument();
  });

  it("adds load, network, and disk I/O cards with host stats", async () => {
    render(<MemoryRouter><AntApp><MonitorPage /></AntApp></MemoryRouter>);
    expect(await screen.findByText("Load")).toBeInTheDocument();
    expect(screen.getByText("1m 0.5 · 5m 0.4 · 15m 0.3")).toBeInTheDocument();
    expect(screen.getByText("Network")).toBeInTheDocument();
    expect(screen.getByText("Disk I/O")).toBeInTheDocument();
    expect(screen.getByText("Uptime: 1 天 1 小时")).toBeInTheDocument();
  });
});
