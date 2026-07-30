import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import MonitorPage from "./MonitorPage";

const { get, navigate } = vi.hoisted(() => ({ get: vi.fn(), navigate: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get } }));
vi.mock("../i18n", () => ({ useI18n: () => ({ t: {
  monitor: { title: "Monitor", refresh: "Refresh", cpu: "CPU", memory: "Memory", disk: "Disk", gpu: "GPU", used: "Used", total: "Total", usage: "Usage" },
} }) }));
vi.mock("react-router-dom", async () => ({
  ...(await vi.importActual<typeof import("react-router-dom")>("react-router-dom")),
  useNavigate: () => navigate,
}));

describe("MonitorPage", () => {
  beforeEach(() => {
    navigate.mockReset();
    get.mockImplementation((url: string) => {
      if (url === "/monitor/current") return Promise.resolve({ data: { cpu: {}, memory: {}, disk: {}, gpu: [] } });
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "Weld line" }] } });
      if (url === "/projects/project-1/spot-weld/warnings") return Promise.resolve({ data: {
        counts: { critical: 1, warning: 0, notice: 0, none: 4 },
        items: [{ id: "sample-1", display_id: "W-0001", run_id: "run-1", warning_level: "critical", defect_probability: 0.91, current_label: "strong_splatter" }],
      } });
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
  });

  it("opens a quality warning in its exact annotation sample", async () => {
    render(<MemoryRouter><AntApp><MonitorPage /></AntApp></MemoryRouter>);

    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "质量预警项目" }));
    fireEvent.click(await screen.findByText("Weld line"));
    expect(await screen.findByText("W-0001")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看样本 W-0001" }));

    expect(navigate).toHaveBeenCalledWith("/data-annotation?projectId=project-1&runId=run-1&sampleId=sample-1");
  });

  it("keeps the newest project's warnings when an earlier request resolves late", async () => {
    let resolveFirst: (value: unknown) => void = () => undefined;
    let resolveSecond: (value: unknown) => void = () => undefined;
    const firstWarningRequest = new Promise((resolve) => { resolveFirst = resolve; });
    const secondWarningRequest = new Promise((resolve) => { resolveSecond = resolve; });
    get.mockImplementation((url: string) => {
      if (url === "/monitor/current") return Promise.resolve({ data: { cpu: {}, memory: {}, disk: {}, gpu: [] } });
      if (url === "/projects") return Promise.resolve({ data: { items: [
        { id: "project-1", name: "Weld line A" },
        { id: "project-2", name: "Weld line B" },
      ] } });
      if (url === "/projects/project-1/spot-weld/warnings") return firstWarningRequest;
      if (url === "/projects/project-2/spot-weld/warnings") return secondWarningRequest;
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(<MemoryRouter><AntApp><MonitorPage /></AntApp></MemoryRouter>);

    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "质量预警项目" }));
    fireEvent.click(await screen.findByText("Weld line A"));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/projects/project-1/spot-weld/warnings"));

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "质量预警项目" }));
    fireEvent.click(await screen.findByText("Weld line B"));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/projects/project-2/spot-weld/warnings"));

    resolveSecond({ data: { counts: { critical: 0, warning: 1, notice: 0, none: 0 }, items: [
      { id: "sample-b", display_id: "W-B", run_id: "run-b", warning_level: "warning" },
    ] } });
    expect(await screen.findByText("W-B")).toBeInTheDocument();

    resolveFirst({ data: { counts: { critical: 1, warning: 0, notice: 0, none: 0 }, items: [
      { id: "sample-a", display_id: "W-A", run_id: "run-a", warning_level: "critical" },
    ] } });
    await waitFor(() => expect(screen.queryByText("W-A")).not.toBeInTheDocument());
    expect(screen.getByText("W-B")).toBeInTheDocument();
  });
});
