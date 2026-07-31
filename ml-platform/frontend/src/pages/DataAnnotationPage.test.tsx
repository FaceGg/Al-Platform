import { App as AntApp } from "antd";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "焊装线", project_role: "owner" }] } });
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

  it("falls back to an accessible project when the URL project is stale", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?projectId=missing-project"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    await waitFor(() => expect(get).toHaveBeenCalledWith("/projects/project-1/spot-weld/runs"));
    expect(get).not.toHaveBeenCalledWith("/projects/missing-project/spot-weld/runs");
    expect(screen.getByLabelText("Project")).toHaveValue("project-1");
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

  it("ignores a sample detail that returns after switching projects", async () => {
    let resolveOldDetail: (value: unknown) => void = () => undefined;
    const oldDetail = new Promise((resolve) => { resolveOldDetail = resolve; });
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [
        { id: "project-1", name: "焊装线 A", project_role: "owner" },
        { id: "project-2", name: "焊装线 B", project_role: "owner" },
      ] } });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [{ id: "run-1", status: "completed" }] } });
      if (url === "/projects/project-2/spot-weld/runs") return Promise.resolve({ data: { items: [{ id: "run-2", status: "completed" }] } });
      if (url.endsWith("/runs/run-1/samples")) return Promise.resolve({ data: { items: [{ id: "sample-1", display_id: "W-0001", review_status: "pending_review" }] } });
      if (url.endsWith("/runs/run-2/samples")) return Promise.resolve({ data: { items: [] } });
      if (url.endsWith("/runs/run-1/samples/sample-1")) return oldDetail;
      return Promise.resolve({ data: { items: [] } });
    });

    render(
      <MemoryRouter initialEntries={["/data-annotation?projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "W-0001" }));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/projects/project-1/spot-weld/runs/run-1/samples/sample-1"));
    fireEvent.change(screen.getByLabelText("Project"), { target: { value: "project-2" } });
    await waitFor(() => expect(get).toHaveBeenCalledWith("/projects/project-2/spot-weld/runs"));
    expect(await screen.findByText("暂无样本")).toBeInTheDocument();

    await act(async () => {
      resolveOldDetail({ data: {
        id: "sample-1", display_id: "W-0001", review_status: "pending_review",
        waveforms: { current: [1], voltage: [2], resistance: [3], power: [4] },
      } });
      await Promise.resolve();
    });

    expect(screen.queryByText("电流")).not.toBeInTheDocument();
    expect(screen.getByText("选择样本查看波形")).toBeInTheDocument();
  });

  it("uploads a report and queues a validated quality run", async () => {
    post.mockImplementation((url: string) => {
      if (url === "/projects/project-1/datasets/upload") return Promise.resolve({ data: { artifact_id: "artifact-1" } });
      if (url.endsWith("/spot-weld/validate")) return Promise.resolve({ data: { valid_rows: 12, errors: [] } });
      if (url.endsWith("/spot-weld/runs")) return Promise.resolve({ data: { id: "run-uploaded", status: "queued" } });
      return Promise.resolve({ data: {} });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    const file = new File(["report"], "spot-weld.csv", { type: "text/csv" });
    fireEvent.change(await screen.findByLabelText("上传点焊报告"), { target: { files: [file] } });

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs",
      { dataset_artifact_id: "artifact-1", field_mapping: {} },
    ));
  });

  it("freezes approved labels before training and exposes the resulting quality model", async () => {
    post.mockImplementation((url: string) => {
      if (url.endsWith("/label-snapshots")) return Promise.resolve({ data: { id: "snapshot-1", name: "approved-labels", sample_count: 10 } });
      if (url.endsWith("/label-snapshots/snapshot-1/train")) return Promise.resolve({ data: {
        snapshot_id: "snapshot-1",
        model: { id: "quality-model-1", name: "点焊质量模型", params: { feature_version: "report_v1" } },
        output_artifacts: { report: "report-1" },
      } });
      return Promise.resolve({ data: {} });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "创建训练快照" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs/run-1/label-snapshots",
      { name: "approved-labels", label_source: "approved" },
    ));
    fireEvent.change(screen.getByLabelText("训练标签快照"), { target: { value: "snapshot-1" } });
    fireEvent.click(screen.getByRole("button", { name: "训练快照" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs/run-1/label-snapshots/snapshot-1/train",
    ));
    expect(await screen.findByText("点焊质量模型")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载质量报告" })).toBeInTheDocument();
  });

  it("creates a clearly sourced automatic-label snapshot", async () => {
    post.mockImplementation((url: string) => {
      if (url.endsWith("/label-snapshots")) return Promise.resolve({ data: {
        id: "snapshot-auto", name: "report-auto", label_source: "automatic", sample_count: 10,
      } });
      return Promise.resolve({ data: {} });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.change(await screen.findByLabelText("快照名称"), { target: { value: "report-auto" } });
    fireEvent.change(screen.getByLabelText("快照标签来源"), { target: { value: "automatic" } });
    fireEvent.click(screen.getByRole("button", { name: "创建训练快照" }));

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs/run-1/label-snapshots",
      { name: "report-auto", label_source: "automatic" },
    ));
    expect(screen.getByRole("option", { name: "report-auto · 报告复现自动标签 · 10 条" })).toBeInTheDocument();
  });

  it("offers 60-row and 1875-row simulated report datasets", async () => {
    post.mockImplementation((url: string, payload: any) => {
      if (url.endsWith("/demo-dataset")) return Promise.resolve({ data: { artifact_id: `artifact-${payload.row_count}` } });
      if (url.endsWith("/validate")) return Promise.resolve({ data: { valid_rows: 12, errors: [] } });
      if (url.endsWith("/runs")) return Promise.resolve({ data: { id: "run-demo", status: "queued" } });
      return Promise.resolve({ data: {} });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /模拟数据/ }));
    expect(await screen.findByText("快速样本（60 条）")).toBeInTheDocument();
    fireEvent.click(screen.getByText("报告复现（1875 条）"));

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/demo-dataset",
      { row_count: 1875 },
    ));
  });
});
