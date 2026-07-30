import { App as AntApp } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DataAnnotationPage from "./DataAnnotationPage";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get, post } }));
vi.mock("echarts", () => ({
  init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }),
}));

describe("DataAnnotationPage", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockResolvedValue({ data: {} });
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "焊装线" }] } });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [{ id: "run-1", status: "completed", sample_count: 1 }] } });
      if (url.endsWith("/samples")) return Promise.resolve({ data: { items: [{ id: "sample-1", display_id: "W-0001", review_status: "pending_review", warning_level: "none" }] } });
      if (url.endsWith("/samples/sample-1")) return Promise.resolve({ data: { id: "sample-1", display_id: "W-0001", review_status: "pending_review", waveforms: { current: [1], voltage: [2], resistance: [3], power: [4] } } });
      return Promise.resolve({ data: { items: [] } });
    });
  });

  it("shows the independent annotation workspace before a quality run exists", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "数据标注" })).toBeInTheDocument();
    expect(screen.getByLabelText("Project")).toBeInTheDocument();
    expect(screen.getByText("样本队列")).toBeInTheDocument();
    expect(screen.getByText("四通道波形")).toBeInTheDocument();
    expect(screen.getByText("标注与审核")).toBeInTheDocument();
  });

  it("loads a sample waveform and submits an operator label", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "W-0001" }));
    expect(await screen.findByText("电流")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("人工标签"), { target: { value: "power_fluctuation" } });
    fireEvent.click(screen.getByRole("button", { name: "提交复核" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs/run-1/samples/sample-1/labels",
      { label: "power_fluctuation", note: "" },
    ));
  });
});
