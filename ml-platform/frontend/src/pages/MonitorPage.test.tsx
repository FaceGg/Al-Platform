import { render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import MonitorPage from "./MonitorPage";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get } }));
vi.mock("../i18n", () => ({ useI18n: () => ({ t: {
  monitor: { title: "Monitor", refresh: "Refresh", cpu: "CPU", memory: "Memory", disk: "Disk", gpu: "GPU", used: "Used", total: "Total", usage: "Usage" },
} }) }));
vi.mock("react-router-dom", async () => ({
  ...(await vi.importActual<typeof import("react-router-dom")>("react-router-dom")),
}));

describe("MonitorPage", () => {
  beforeEach(() => {
    get.mockImplementation((url: string) => {
      if (url === "/monitor/current") return Promise.resolve({ data: { cpu: {}, memory: {}, disk: {}, gpu: [] } });
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
  });

  it("shows resource metrics without the removed quality warning panel", async () => {
    render(<MemoryRouter><AntApp><MonitorPage /></AntApp></MemoryRouter>);
    expect(await screen.findByText("CPU")).toBeInTheDocument();
    expect(screen.queryByText("点焊质量预警")).not.toBeInTheDocument();
  });

});
