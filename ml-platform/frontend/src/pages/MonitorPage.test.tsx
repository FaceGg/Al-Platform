import { render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import MonitorPage from "./MonitorPage";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get } }));
vi.mock("../i18n", () => ({ useI18n: () => ({ t: {
  monitor: { title: "Monitor", refresh: "Refresh", cpu: "CPU", memory: "Memory", disk: "Disk", gpu: "GPU", used: "Used", total: "Total", usage: "Usage", temperature: "Temp", no_gpu: "No GPU detected" },
} }) }));
vi.mock("react-router-dom", async () => ({
  ...(await vi.importActual<typeof import("react-router-dom")>("react-router-dom")),
}));

function mockCurrent(gpu: any[]) {
  get.mockImplementation((url: string) => {
    if (url === "/monitor/current") return Promise.resolve({ data: { cpu: { percent: 12 }, memory: {}, disk: {}, gpu } });
    if (url === "/monitor/history") return Promise.resolve({ data: [
      { cpu: { percent: 5 }, memory: { percent: 30 }, disk: { percent: 40 }, gpu: gpu.map((g) => ({ gpu_util: g.gpu_util - 1 })) },
      { cpu: { percent: 8 }, memory: { percent: 32 }, disk: { percent: 41 }, gpu: gpu.map((g) => ({ gpu_util: g.gpu_util })) },
    ] });
    return Promise.reject(new Error(`Unexpected URL: ${url}`));
  });
}

describe("MonitorPage", () => {
  beforeEach(() => {
    mockCurrent([]);
  });

  it("shows resource metrics without the removed quality warning panel", async () => {
    render(<MemoryRouter><AntApp><MonitorPage /></AntApp></MemoryRouter>);
    expect(await screen.findByText("CPU")).toBeInTheDocument();
    expect(screen.queryByText("点焊质量预警")).not.toBeInTheDocument();
  });

  it("backfills trend lines from the backend history buffer on mount", async () => {
    render(<MemoryRouter><AntApp><MonitorPage /></AntApp></MemoryRouter>);
    await screen.findByText("CPU");
    await Promise.resolve();
    expect(get).toHaveBeenCalledWith("/monitor/history", { params: { limit: 60 } });
  });

  it("renders one card per GPU when multiple GPUs are detected", async () => {
    mockCurrent([
      { gpu_util: 61, memory_used_mb: 2048, memory_total_mb: 8192, temperature_c: 67 },
      { gpu_util: 22, memory_used_mb: 1024, memory_total_mb: 8192, temperature_c: 54 },
    ]);
    render(<MemoryRouter><AntApp><MonitorPage /></AntApp></MemoryRouter>);
    expect(await screen.findByText("GPU 1")).toBeInTheDocument();
    expect(screen.getByText("GPU 2")).toBeInTheDocument();
    expect(screen.getByText("Temp: 67°C")).toBeInTheDocument();
  });

  it("keeps a single GPU card and notes when no GPU is detected", async () => {
    render(<MemoryRouter><AntApp><MonitorPage /></AntApp></MemoryRouter>);
    expect(await screen.findByText("No GPU detected")).toBeInTheDocument();
    const gpuHeadings = screen.getAllByText("GPU");
    expect(gpuHeadings.length).toBeGreaterThan(0);
  });

});
