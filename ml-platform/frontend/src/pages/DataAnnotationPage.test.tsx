import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { App as AntApp } from "antd";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DataAnnotationPage from "./DataAnnotationPage";

const { get, post, datasets } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), datasets: vi.fn() }));
const quality = vi.hoisted(() => ({ saveLabeledDataset: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get, post } }));
vi.mock("../api/datasets", () => ({ listDatasets: datasets }));
vi.mock("../api/spotWeldQuality", async () => {
  const actual = await vi.importActual<typeof import("../api/spotWeldQuality")>("../api/spotWeldQuality");
  return { ...actual, saveLabeledDataset: quality.saveLabeledDataset };
});
vi.mock("echarts", () => ({
  init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }),
}));

describe("DataAnnotationPage", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockResolvedValue({ data: {} });
    datasets.mockReset();
    datasets.mockResolvedValue([
      { id: "dataset-report", artifact_id: "dataset-report", name: "weld-report.csv", format: "csv", row_count: 12 },
      { id: "dataset-image", artifact_id: "dataset-image", name: "weld-image.png", format: "png", row_count: 1 },
    ]);
    quality.saveLabeledDataset.mockReset();
    quality.saveLabeledDataset.mockResolvedValue({ artifact_id: "saved-1", name: "weld-labeled.csv" });
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "焊装线", project_role: "owner" }] } });
      if (url === "/datasets?project_id=project-1") return Promise.resolve({ data: { items: [
        { id: "dataset-report", artifact_id: "dataset-report", name: "weld-report.csv", format: "csv", row_count: 12 },
        { id: "dataset-image", artifact_id: "dataset-image", name: "weld-image.png", format: "png", row_count: 1 },
      ] } });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [
        {
          id: "run-1",
          status: "completed",
          sample_count: 1,
          label_mode: "automatic",
          annotation_progress: { annotated_count: 1, total_count: 1, percent: 100 },
        },
        {
          id: "run-manual",
          status: "completed",
          sample_count: 4,
          label_mode: "manual",
          annotation_progress: { annotated_count: 2, total_count: 4, percent: 50 },
        },
      ] } });
      if (url.endsWith("/samples")) return Promise.resolve({ data: { items: [{ id: "sample-1", display_id: "W-0001", review_status: "pending_review", warning_level: "none" }] } });
      if (url.endsWith("/samples/sample-1")) return Promise.resolve({ data: { id: "sample-1", display_id: "W-0001", review_status: "pending_review", waveforms: { current: [1], voltage: [2], resistance: [3], power: [4] } } });
      return Promise.resolve({ data: { items: [] } });
    });
  });

  it("shows five annotation types before a user selects a workflow", async () => {
    render(
      <MemoryRouter>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "数据标注" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "点焊数据标注" })).toBeInTheDocument();
    expect(screen.getByText("电极柱极焊数据标注")).toBeInTheDocument();
    expect(screen.getByText("加注数据标注")).toBeInTheDocument();
    expect(screen.getByText("拧紧数据标注")).toBeInTheDocument();
    expect(screen.getByText("其他")).toBeInTheDocument();
    expect(screen.queryByText("样本队列")).not.toBeInTheDocument();
  });

  it("opens point-weld setup with compatible data-management files", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "点焊数据标注" }));
    });
    expect(await screen.findByRole("heading", { name: "点焊标注任务" })).toBeInTheDocument();
    expect(screen.getByText("自动标注")).toBeInTheDocument();
    expect(screen.getByText("1/1 100%")).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "新建自动标注任务" }));
      await Promise.resolve();
    });
    expect(await screen.findByRole("heading", { name: "点焊标注配置" })).toBeInTheDocument();
    expect(screen.getByLabelText("数据管理文件")).toBeInTheDocument();
    expect(screen.getByText("自动标注规则")).toBeInTheDocument();
  });

  it("loads compatible data-management files from an automatic-label setup link", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=setup&mode=automatic&projectId=project-1&datasetId=dataset-report"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    await waitFor(() => expect(datasets).toHaveBeenCalledWith("project-1"));
    expect(await screen.findByRole("option", { name: "weld-report.csv · 12 行" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /weld-image\.png/ })).not.toBeInTheDocument();
  });

  it("opens a manual task directly in the annotation workspace", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=tasks&projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "手工标注 run-manual" }));

    expect(await screen.findByText("样本队列")).toBeInTheDocument();
    expect(screen.getByText("2/4 50%")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "上传报告" })).not.toBeInTheDocument();
  });

  it("offers annotation export after a project and run are selected", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("button", { name: "导出标注" })).toBeInTheDocument();
    const styles = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8");
    expect(styles).toContain(".spot-weld-annotation__sample-list");
    expect(styles).toContain("overflow-y: auto");
  });

  it("falls back to an accessible project when the URL project is stale", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=setup&projectId=missing-project"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    await waitFor(() => expect(get).toHaveBeenCalledWith("/projects/project-1/spot-weld/runs"));
    expect(get).not.toHaveBeenCalledWith("/projects/missing-project/spot-weld/runs");
    expect(screen.getByLabelText("Project")).toHaveValue("project-1");
  });

  it("loads a sample waveform and submits an operator label", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
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

  it("renders all configured quality labels for automatic evidence and manual correction", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "焊装线", project_role: "owner" }] } });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [{ id: "run-1", status: "completed", sample_count: 1 }] } });
      if (url.endsWith("/samples")) return Promise.resolve({ data: { items: [{ id: "sample-1", display_id: "W-0001", review_status: "pending_review", warning_level: "notice" }] } });
      if (url.endsWith("/samples/sample-1")) return Promise.resolve({ data: {
        id: "sample-1",
        display_id: "W-0001",
        review_status: "pending_review",
        automatic_label: "anomaly_cluster",
        cluster_id: 1,
        rule_hits: [{ code: "anomaly_cluster", label: "anomaly_cluster", reason: "cluster=1 and wld_spatter_strength >= 2" }],
        waveforms: { current: [1], voltage: [2], resistance: [3], power: [4] },
      } });
      return Promise.resolve({ data: { items: [] } });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "W-0001" }));
    const automaticLabel = await screen.findByText("自动标签");
    expect(within(automaticLabel.parentElement as HTMLElement).getByText("飞溅倾向簇")).toBeInTheDocument();
    expect(screen.getByText("cluster=1 且 飞溅等级 >= 2")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "电流波形异常" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "飞溅倾向簇" })).toBeInTheDocument();
  });

  it("offers saving confirmed labels back to data management", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("button", { name: "保存到数据管理" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存到数据管理" }));
    await waitFor(() => expect(quality.saveLabeledDataset).toHaveBeenCalledWith("project-1", "run-1", "current"));
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
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
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

  it("uses edited automatic rules when it creates a quality run", async () => {
    post.mockImplementation((url: string) => {
      if (url === "/projects/project-1/datasets/upload") return Promise.resolve({ data: { artifact_id: "artifact-1" } });
      if (url.endsWith("/spot-weld/validate")) return Promise.resolve({ data: { valid_rows: 12, errors: [] } });
      if (url.endsWith("/spot-weld/runs")) return Promise.resolve({ data: { id: "run-uploaded", status: "queued" } });
      return Promise.resolve({ data: {} });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=setup&projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    const file = new File(["report"], "spot-weld.csv", { type: "text/csv" });
    fireEvent.change(await screen.findByLabelText("上传点焊报告"), { target: { files: [file] } });

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/datasets/upload",
      expect.any(FormData),
    ));
    fireEvent.change(screen.getByLabelText("强飞溅阈值"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "开始自动标注" }));

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs",
      {
        dataset_artifact_id: "artifact-1",
        field_mapping: {},
        candidate_ids: [],
        label_mode: "automatic",
        rule_config: {
          strong_splatter_min: 4,
          weak_splatter_value: 2,
          spotdiameter_small_min: 0,
          spotdiameter_small_max: 2,
          spotdiameter_large_min: 80,
          energy_dev_sigma: 2.5,
          current_max_diff_percentile: 95,
          power_std_percentile: 95,
          spatter_cluster_id: 1,
          spatter_cluster_min_strength: 2,
        },
      },
    ));
  });

  it("creates a manual point-weld run without automatic rule labels", async () => {
    post.mockImplementation((url: string) => {
      if (url.endsWith("/spot-weld/validate")) return Promise.resolve({ data: { valid_rows: 12, errors: [] } });
      if (url.endsWith("/spot-weld/runs")) return Promise.resolve({ data: { id: "run-manual", status: "queued" } });
      return Promise.resolve({ data: {} });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&datasetId=dataset-report"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("radio", { name: "手动标注" }));
    fireEvent.click(screen.getByRole("button", { name: "开始手动标注" }));

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs",
      {
        dataset_artifact_id: "dataset-report",
        field_mapping: {},
        candidate_ids: [],
        label_mode: "manual",
      },
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
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
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
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
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
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=setup&projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
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
