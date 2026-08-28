import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { App as AntApp } from "antd";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DataAnnotationPage from "./DataAnnotationPage";
import { translations } from "../i18n";

const { get, post, put, remove, datasets } = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(), remove: vi.fn(), datasets: vi.fn(),
}));
const quality = vi.hoisted(() => ({ saveLabeledDataset: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get, post, put, delete: remove } }));
vi.mock("../api/datasets", () => ({ listDatasets: datasets }));
vi.mock("../api/spotWeldQuality", async () => {
  const actual = await vi.importActual<typeof import("../api/spotWeldQuality")>("../api/spotWeldQuality");
  return { ...actual, saveLabeledDataset: quality.saveLabeledDataset };
});
vi.mock("echarts", () => ({
  init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }),
}));

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="annotation-location">{location.pathname}{location.search}</output>;
}

function BrowserBackButton() {
  const navigate = useNavigate();
  return <button type="button" onClick={() => navigate(-1)}>browser-back</button>;
}

describe("DataAnnotationPage", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    get.mockReset();
    post.mockResolvedValue({ data: {} });
    put.mockReset();
    put.mockResolvedValue({ data: {} });
    remove.mockReset();
    remove.mockResolvedValue({ data: { deleted: 1, run_id: "run-1" } });
    datasets.mockReset();
    datasets.mockResolvedValue([
      { id: "dataset-report", artifact_id: "dataset-report", name: "customer-data.csv", format: "csv", row_count: 12 },
      { id: "dataset-image", artifact_id: "dataset-image", name: "sample-image.png", format: "png", row_count: 1 },
    ]);
    quality.saveLabeledDataset.mockReset();
    quality.saveLabeledDataset.mockResolvedValue({ artifact_id: "saved-1", name: "labeled-data.csv" });
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "焊装线", project_role: "owner" }] } });
      if (url === "/datasets?project_id=project-1") return Promise.resolve({ data: { items: [
        { id: "dataset-report", artifact_id: "dataset-report", name: "customer-data.csv", format: "csv", row_count: 12 },
        { id: "dataset-image", artifact_id: "dataset-image", name: "sample-image.png", format: "png", row_count: 1 },
      ] } });
      if (url === "/spot-weld/runs" || url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [
        {
          id: "run-1",
          project_id: "project-1",
          project_name: "焊装线",
          created_by_name: "alice",
          status: "completed",
          sample_count: 1,
          label_mode: "automatic",
          target_schema: { name: "Fault", dtype: "int64", classes: ["0", "1"] },
          annotation_progress: { annotated_count: 1, total_count: 1, percent: 100 },
        },
        {
          id: "run-manual",
          project_id: "project-1",
          project_name: "焊装线",
          created_by_name: "bob",
          status: "running",
          sample_count: 4,
          label_mode: "manual",
          annotation_progress: { annotated_count: 2, total_count: 4, percent: 50 },
        },
      ] } });
      if (url.includes("/spot-weld/datasets/") && url.endsWith("/columns")) return Promise.resolve({ data: {
        columns: [{ name: "wld1c", dtype: "float64" }, { name: "Fault", dtype: "object" }],
        row_count: 12,
        target_candidates: ["wld1c", "Fault"],
      } });
      if (url === "/projects/project-1/spot-weld/models") return Promise.resolve({ data: { items: [{
        id: "model-1", name: "分类模型", version: "v1", status: "completed", framework: "scikit-learn",
        registered_model_id: "registered-1", model_version_id: "version-1",
        feature_schema: [{ name: "wld1c", dtype: "float64" }],
        label_dtype: "int64", target_column: "Fault", target_column_dtype: "int64",
      }] } });
      if (url.endsWith("/samples")) return Promise.resolve({ data: { items: [{ id: "sample-1", display_id: "W-0001", review_status: "pending_review", warning_level: "none" }] } });
      if (url.endsWith("/samples/sample-1")) return Promise.resolve({ data: { id: "sample-1", display_id: "W-0001", review_status: "pending_review", table_values: { feature_a: 1 }, waveforms: { current: [], voltage: [], resistance: [], power: [] } } });
      return Promise.resolve({ data: { items: [] } });
    });
  });

  it("opens the task list directly without annotation type cards", async () => {
    render(
      <MemoryRouter>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("button", { name: "新建手动标注任务" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新建自动标注任务" })).toBeInTheDocument();
    const taskList = screen.getByRole("region", { name: "数据标注任务列表" });
    expect(taskList).toBeInTheDocument();
    expect(taskList).toHaveClass("table-surface");
    expect(within(taskList).getByRole("columnheader", { name: "任务" })).toBeInTheDocument();
    expect(within(taskList).getByRole("columnheader", { name: "项目" })).toBeInTheDocument();
    expect(within(taskList).getByRole("columnheader", { name: "创建者" })).toBeInTheDocument();
    expect(within(taskList).getByRole("columnheader", { name: "操作" })).toBeInTheDocument();
    expect(taskList.querySelector("article")).not.toBeInTheDocument();
    expect(screen.queryByText("SPOT WELD / TASKS")).not.toBeInTheDocument();
    expect(screen.queryByText("点焊标注任务")).not.toBeInTheDocument();
    expect(screen.queryByText("查看任务状态、标注方式和当前进度")).not.toBeInTheDocument();
    expect(await screen.findByText("1/1 100%")).toBeInTheDocument();
    expect(within(taskList).getAllByText("焊装线")).toHaveLength(2);
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.queryByText("电极柱极焊数据标注")).not.toBeInTheDocument();
  });

  it("opens generic setup with compatible data-management files", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("button", { name: "新建自动标注任务" })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "新建自动标注任务" }));
      await Promise.resolve();
    });
    expect(await screen.findByRole("heading", { name: "新建自动标注任务" })).toBeInTheDocument();
    expect(screen.getByLabelText("数据管理文件")).toBeInTheDocument();
    expect(screen.queryByLabelText("目标列来源")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("目标列")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /下一页/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /下一页/ }).parentElement).toHaveClass("data-annotation__setup-footer--centered");
    expect(screen.queryByLabelText("弱监督标注策略")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "开始自动标注" })).not.toBeInTheDocument();
    expect(screen.queryByText("准备模拟数据")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("已有质量运行")).not.toBeInTheDocument();
  });

  it("loads compatible data-management files from an automatic-label setup link", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=setup&mode=automatic&projectId=project-1&datasetId=dataset-report"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    await waitFor(() => expect(datasets).toHaveBeenCalledWith("project-1"));
    expect(await screen.findByRole("option", { name: "customer-data.csv · 12 行" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /sample-image\.png/ })).not.toBeInTheDocument();
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

  it("deletes an annotation task after confirmation", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=tasks&projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "删除标注任务 run-manual" }));
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(within(await screen.findByRole("tooltip")).getByRole("button", { name: /删\s*除/ }));

    await waitFor(() => expect(remove).toHaveBeenCalledWith("/projects/project-1/spot-weld/runs/run-manual"));
  });

  it("provides English copy for the weak-supervision fallback rule", () => {
    expect(translations.en.dataAnnotation.fallbackLabel).toBe("Other");
    expect(translations.en.dataAnnotation.fallbackCondition).toBe("All other cases");
  });

  it("does not delete an annotation task when confirmation is cancelled", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=tasks&projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "删除标注任务 run-manual" }));
    fireEvent.click(within(await screen.findByRole("tooltip")).getByRole("button", { name: /取\s*消/ }));

    expect(remove).not.toHaveBeenCalled();
  });

  it("shows task actions in the task-list header and keeps delete available for every task", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=tasks&projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    const list = await screen.findByRole("region", { name: "数据标注任务列表" });
    expect(screen.getByRole("heading", { name: "标注任务" })).toBeInTheDocument();
    expect(list.closest(".table-surface")).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: "删除标注任务 run-1" })).toBeEnabled();
    expect(within(list).getByRole("button", { name: "删除标注任务 run-manual" })).toBeEnabled();
  });

  it("loads every accessible project's tasks and shows project and creator columns", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [
        { id: "project-1", name: "焊装线", project_role: "owner" },
        { id: "project-2", name: "总装线", project_role: "editor" },
      ] } });
      if (url === "/spot-weld/runs") return Promise.resolve({ data: { items: [
        { id: "run-1", project_id: "project-1", project_name: "焊装线", created_by_name: "alice", status: "completed", label_mode: "automatic", annotation_progress: { annotated_count: 1, total_count: 1, percent: 100 } },
        { id: "run-2", project_id: "project-2", project_name: "总装线", created_by_name: "carol", status: "completed", label_mode: "manual", annotation_progress: { annotated_count: 2, total_count: 2, percent: 100 } },
      ] } });
      return Promise.resolve({ data: { items: [] } });
    });
    render(<MemoryRouter initialEntries={["/data-annotation?view=tasks"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AntApp><DataAnnotationPage /></AntApp></MemoryRouter>);
    const list = await screen.findByRole("region", { name: "数据标注任务列表" });
    await waitFor(() => expect(get).toHaveBeenCalledWith("/spot-weld/runs"));
    expect(within(list).getByText("焊装线")).toBeInTheDocument();
    expect(within(list).getByText("总装线")).toBeInTheDocument();
    expect(within(list).getByText("alice")).toBeInTheDocument();
    expect(within(list).getByText("carol")).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: "查看标注 run-1" })).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: "手工标注 run-2" })).toBeInTheDocument();
  });

  it("limits manual task status display to running or completed while preserving automatic statuses", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "焊装线", project_role: "owner" }] } });
      if (url === "/spot-weld/runs") return Promise.resolve({ data: { items: [
        { id: "manual-failed", project_id: "project-1", project_name: "焊装线", created_by_name: "alice", status: "failed", label_mode: "manual" },
        { id: "manual-cancelled", project_id: "project-1", project_name: "焊装线", created_by_name: "bob", status: "cancelled", label_mode: "manual" },
        { id: "automatic-failed", project_id: "project-1", project_name: "焊装线", created_by_name: "carol", status: "failed", label_mode: "automatic" },
      ] } });
      return Promise.resolve({ data: { items: [] } });
    });

    render(<MemoryRouter initialEntries={["/data-annotation?view=tasks"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AntApp><DataAnnotationPage /></AntApp></MemoryRouter>);

    const list = await screen.findByRole("region", { name: "数据标注任务列表" });
    expect(within(list).getAllByText("运行中")).toHaveLength(2);
    expect(within(list).getByText("失败")).toBeInTheDocument();
  });

  it("does not show domain-specific rules after automatic task creation", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=workspace&projectId=project-1&runId=run-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "W-0001" }));
    expect(await screen.findByText("当前样本数据")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/点焊|焊点|飞溅|虚焊|烧穿|波形|工艺规则/);
  });

  it("does not show process rules for manual tasks", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=workspace&projectId=project-1&runId=run-manual&mode=manual"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "W-0001" }));
    expect(await screen.findByRole("heading", { name: "人工标签" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "工艺规则" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "标注规则" })).not.toBeInTheDocument();
  });

  it("refreshes an active run and its sample queue every second", async () => {
    vi.useFakeTimers();
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "焊装线", project_role: "owner" }] } });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [{
        id: "run-live", status: "running", label_mode: "automatic",
        annotation_progress: { annotated_count: 0, total_count: 10, percent: 0 },
      }] } });
      if (url === "/projects/project-1/spot-weld/runs/run-live") return Promise.resolve({ data: {
        id: "run-live", status: "running", label_mode: "automatic",
        annotation_progress: { annotated_count: 5, total_count: 10, percent: 50 },
      } });
      if (url.endsWith("/runs/run-live/samples")) return Promise.resolve({ data: { items: [] } });
      return Promise.resolve({ data: { items: [] } });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=workspace&projectId=project-1&runId=run-live"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    get.mockClear();

    await act(async () => { vi.advanceTimersByTime(1000); await Promise.resolve(); await Promise.resolve(); });

    expect(get).toHaveBeenCalledWith("/projects/project-1/spot-weld/runs/run-live");
    expect(get).toHaveBeenCalledWith("/projects/project-1/spot-weld/runs/run-live/samples", { params: {} });
    expect(get).not.toHaveBeenCalledWith("/projects/project-1/spot-weld/runs/run-live/samples/sample-1");
    vi.useRealTimers();
  });

  it("returns to the task list in one action and clears workspace parameters", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=workspace&projectId=project-1&datasetId=dataset-report&runId=run-1&sampleId=sample-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <LocationProbe />
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "返回任务列表" }));

    expect(await screen.findByRole("button", { name: "新建手动标注任务" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("annotation-location")).toHaveTextContent("view=tasks"));
    expect(screen.getByTestId("annotation-location")).not.toHaveTextContent("runId=");
    expect(screen.getByTestId("annotation-location")).not.toHaveTextContent("datasetId=");
    expect(screen.getByTestId("annotation-location")).not.toHaveTextContent("sampleId=");
  });

  it("uses compact rule and sample-data panels in the annotation detail view", () => {
    const styles = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8").replace(/\r\n/g, "\n");
    expect(styles).toContain(".spot-weld-annotation__rule-list {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));");
    expect(styles).toContain("max-block-size: min(48vh, 520px);");
    expect(styles).toContain("padding: 4px 6px;");
    expect(styles).not.toContain(".spot-weld-annotation__raw-data-row.is-matched");
    expect(styles).not.toContain(".spot-weld-annotation__raw-data-row.is-unmatched");
  });

  it("keeps the annotation detail header compact", () => {
    const styles = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8").replace(/\r\n/g, "\n");
    expect(styles).toContain(".spot-weld-annotation__workspace-header {\n  min-height: 0;\n  align-items: center;\n  gap: 10px;\n  margin-bottom: 8px;\n  padding: 5px 10px;");
    expect(styles).toContain(".spot-weld-annotation__workspace-header .page-title {\n  font-size: 15px;");
    expect(styles).not.toContain(".spot-weld-annotation__workspace-header .spot-weld-annotation__project");
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

  it("loads a sample detail and saves an operator label", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "W-0001" }));
    expect(await screen.findByText("当前样本数据")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "编辑" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "删除人工标签" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "1" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs/run-1/samples/sample-1/labels",
      { label: "1", note: "" },
    ));
  });

  it("uses edit mode for the label list without hiding sample label choices", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "W-0001" }));
    expect(await screen.findByText("当前样本数据")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "0" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));

    expect(screen.getByRole("textbox", { name: "新建人工标签" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "添加标签" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "0" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "删除人工标签 0" })).toBeInTheDocument();
  });

  it("keeps label editing open during polling and sizes options from the longest label", async () => {
    vi.useFakeTimers();
    const run = {
      id: "run-manual-live",
      status: "running",
      label_mode: "manual",
      target_schema: { name: "Fault", dtype: "string", classes: ["短", "这是最长人工标签"] },
      annotation_progress: { annotated_count: 0, total_count: 1, percent: 0 },
    };
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "通用数据项目", project_role: "owner" }] } });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [{ ...run, target_schema: { ...run.target_schema } }] } });
      if (url === "/projects/project-1/spot-weld/runs/run-manual-live") return Promise.resolve({ data: { ...run, target_schema: { ...run.target_schema } } });
      if (url.endsWith("/samples/sample-1")) return Promise.resolve({ data: {
        id: "sample-1", display_id: "W-0001", review_status: "pending_review",
        waveforms: { current: [], voltage: [], resistance: [], power: [] },
      } });
      if (url.endsWith("/samples")) return Promise.resolve({ data: { items: [{ id: "sample-1", display_id: "W-0001", review_status: "pending_review" }] } });
      return Promise.resolve({ data: { items: [] } });
    });

    render(<MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=workspace&projectId=project-1&runId=run-manual-live"]}><AntApp><DataAnnotationPage /></AntApp></MemoryRouter>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.queryByRole("combobox", { name: "Project" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "W-0001" }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));

    const options = screen.getByRole("group", { name: "人工标签选项" });
    expect(options.getAttribute("style")).toContain("--label-option-width: calc(8ch + 68px)");
    await act(async () => { vi.advanceTimersByTime(1000); await Promise.resolve(); await Promise.resolve(); });

    const input = screen.getByRole("textbox", { name: "新建人工标签" });
    fireEvent.change(input, { target: { value: "新增标签" } });
    fireEvent.click(screen.getByRole("button", { name: "添加标签" }));
    expect(screen.getByRole("button", { name: "新增标签" })).toBeInTheDocument();
  });

  it("shows every real sample field, keeps automatic labels unselected, and saves a clicked label", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "通用数据项目", project_role: "owner" }] } });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [{
        id: "run-1", status: "completed", label_mode: "automatic",
        target_schema: { name: "decision", dtype: "string", classes: ["accepted", "rejected"] },
      }] } });
      if (url.endsWith("/samples")) return Promise.resolve({ data: { items: [{ id: "sample-1", display_id: "W-0001", review_status: "pending_review", warning_level: "none" }] } });
      if (url.endsWith("/samples/sample-1")) return Promise.resolve({ data: {
        id: "sample-1",
        display_id: "W-0001",
        automatic_label: "accepted",
        current_label: null,
        review_status: "pending_review",
        table_values: {
          feature_a: 10,
          signal_payload: "source-values",
          custom_flag: "retained",
        },
        feature_values: { feature_a: 10 },
        waveforms: { current: [], voltage: [], resistance: [], power: [] },
      } });
      return Promise.resolve({ data: { items: [] } });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=workspace&projectId=project-1&runId=run-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "W-0001" }));

    expect(await screen.findByRole("button", { name: "返回任务列表" })).toBeInTheDocument();
    expect(screen.getByText("feature_a")).toBeInTheDocument();
    expect(screen.getByText("signal_payload")).toBeInTheDocument();
    expect(screen.getByText("custom_flag")).toBeInTheDocument();
    expect(screen.getByText("retained")).toBeInTheDocument();
    expect(screen.getByText("source-values")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "accepted" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "编辑" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "删除人工标签" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "rejected" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs/run-1/samples/sample-1/labels",
      { label: "rejected", note: "" },
    ));
  });

  it("renders only target-schema labels for automatic correction", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "通用数据项目", project_role: "owner" }] } });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [{
        id: "run-1", status: "completed", sample_count: 1, label_mode: "automatic",
        target_schema: { name: "category", dtype: "string", classes: ["alpha", "beta"] },
      }] } });
      if (url.endsWith("/samples")) return Promise.resolve({ data: { items: [{ id: "sample-1", display_id: "W-0001", review_status: "pending_review", warning_level: "notice" }] } });
      if (url.endsWith("/samples/sample-1")) return Promise.resolve({ data: {
        id: "sample-1",
        display_id: "W-0001",
        review_status: "pending_review",
        automatic_label: "alpha",
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
    expect(await screen.findByRole("button", { name: "alpha" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "beta" })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/点焊|焊点|飞溅|虚焊|烧穿|波形|工艺规则/);
  });

  it("shows only user rule labels for weak-supervision correction", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "通用数据项目", project_role: "owner" }] } });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [{
        id: "run-weak", status: "completed", sample_count: 1, label_mode: "automatic", weak_supervision: true,
        target_schema: { name: null, dtype: "string", classes: ["rule-ok", "rule-defect"] },
      }] } });
      if (url.endsWith("/samples")) return Promise.resolve({ data: { items: [{ id: "sample-1", display_id: "W-0001", review_status: "pending_review", warning_level: "none" }] } });
      if (url.endsWith("/samples/sample-1")) return Promise.resolve({ data: {
        id: "sample-1", display_id: "W-0001", review_status: "pending_review", automatic_label: "model-only",
        waveforms: { current: [1], voltage: [2], resistance: [3], power: [4] },
      } });
      return Promise.resolve({ data: { items: [] } });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-weak"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "W-0001" }));
    expect(await screen.findByRole("button", { name: "rule-ok" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "rule-defect" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "model-only" })).not.toBeInTheDocument();
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

  it("does not render a project switcher in the active workspace", async () => {
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
    expect(screen.queryByRole("combobox", { name: "Project" })).not.toBeInTheDocument();

    await act(async () => {
      resolveOldDetail({ data: {
        id: "sample-1", display_id: "W-0001", review_status: "pending_review",
        waveforms: { current: [1], voltage: [2], resistance: [3], power: [4] },
      } });
      await Promise.resolve();
    });

    expect(screen.getByText("当前样本数据")).toBeInTheDocument();
  });

  it("creates an automatic task in two steps using the registered model output schema", async () => {
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

    fireEvent.change(await screen.findByLabelText("数据管理文件"), { target: { value: "dataset-report" } });
    fireEvent.change(screen.getByLabelText("选择模型"), { target: { value: "model-1" } });
    expect(screen.queryByLabelText("弱监督标注策略")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /下一页/ })).not.toBeDisabled());
    fireEvent.click(await screen.findByRole("button", { name: /下一页/ }));
    expect(screen.getByLabelText("标注策略")).toHaveValue("model-inference");
    expect(screen.getByLabelText("已选模型")).toHaveValue("分类模型 · v1");
    expect(screen.getByRole("button", { name: /上一页/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /上一页/ }).parentElement).toHaveClass("data-annotation__setup-footer--centered");
    fireEvent.click(screen.getByRole("button", { name: "开始自动标注" }));

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs",
      {
        dataset_artifact_id: "dataset-report",
        field_mapping: {},
        algorithm_ids: [],
        search_method: "bayesian",
        max_trials: 20,
        time_budget: 600,
        label_mode: "automatic",
        workflow_kind: "data_annotation",
        label_dtype: "int",
        selected_model_id: "model-1",
        weak_supervision: false,
        process_rules: undefined,
        cluster_labels: undefined,
      },
    ));
  });

  it("uses a generic model-inference strategy without point-weld domain controls", async () => {
    post.mockImplementation((url: string) => {
      if (url.endsWith("/validate")) return Promise.resolve({ data: { valid_rows: 12, errors: [] } });
      if (url.endsWith("/runs")) return Promise.resolve({ data: { id: "run-generic", status: "queued" } });
      return Promise.resolve({ data: {} });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=setup&mode=automatic&projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.change(await screen.findByLabelText("数据管理文件"), { target: { value: "dataset-report" } });
    fireEvent.change(screen.getByLabelText("选择模型"), { target: { value: "model-1" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /下一页/ })).not.toBeDisabled());
    fireEvent.click(await screen.findByRole("button", { name: /下一页/ }));
    expect(screen.getByLabelText("标注策略")).toHaveValue("model-inference");
    expect(screen.getByRole("checkbox", { name: "弱监督标注策略" })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/点焊|焊点|飞溅|虚焊|烧穿|波形|工艺规则/);
    expect(screen.getByRole("button", { name: "开始自动标注" })).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "开始自动标注" }));

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/validate",
      expect.objectContaining({
        label_mode: "automatic",
        selected_model_id: "model-1",
        label_dtype: "int",
      }),
    ));
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs",
      expect.objectContaining({ weak_supervision: false }),
    ));
  });

  it("starts automatic annotation without a target-column or feature-column contract", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "焊装线", project_role: "owner" }] } });
      if (url.includes("/spot-weld/datasets/") && url.endsWith("/columns")) return Promise.resolve({ data: {
        columns: [{ name: "wld1c", dtype: "float64" }], row_count: 12, target_candidates: ["wld1c"],
      } });
      if (url === "/projects/project-1/spot-weld/models") return Promise.resolve({ data: { items: [{
        id: "model-1", name: "分类模型", version: "v1", status: "completed", framework: "scikit-learn",
        feature_schema: [{ name: "wld1c", dtype: "float64" }], label_dtype: "int64", target_column: "Fault", target_column_dtype: "int64",
      }] } });
      return Promise.resolve({ data: { items: [] } });
    });
    post.mockImplementation((url: string) => {
      if (url.endsWith("/validate")) return Promise.resolve({ data: { valid_rows: 12, errors: [] } });
      if (url.endsWith("/runs")) return Promise.resolve({ data: { id: "run-no-target", status: "queued" } });
      return Promise.resolve({ data: {} });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=setup&mode=automatic&projectId=project-1&datasetId=dataset-report"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.change(await screen.findByLabelText("选择模型"), { target: { value: "model-1" } });
    const nextButton = await screen.findByRole("button", { name: /下一页/ });
    await waitFor(() => expect(nextButton).not.toBeDisabled());
    fireEvent.click(nextButton);
    fireEvent.click(await screen.findByRole("button", { name: "开始自动标注" }));

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs",
      expect.objectContaining({
        label_dtype: "int",
        weak_supervision: false,
      }),
    ));
    const automaticPayload = post.mock.calls.find(([url]) => url === "/projects/project-1/spot-weld/runs")?.[1];
    expect(automaticPayload).not.toHaveProperty("target_column");
    expect(automaticPayload).not.toHaveProperty("target_column_created");
    expect(automaticPayload).not.toHaveProperty("target_column_dtype");
    expect(automaticPayload).not.toHaveProperty("input_columns");
  });

  it("returns to the annotation task list when browser back is used after task creation", async () => {
    post.mockImplementation((url: string) => {
      if (url.endsWith("/validate")) return Promise.resolve({ data: { valid_rows: 12, errors: [] } });
      if (url.endsWith("/runs")) return Promise.resolve({ data: {
        id: "run-created", project_id: "project-1", status: "queued", label_mode: "automatic",
      } });
      return Promise.resolve({ data: {} });
    });
    render(
      <MemoryRouter
        initialEntries={[
          "/automl",
          "/data-annotation?view=setup&mode=automatic&projectId=project-1&datasetId=dataset-report",
        ]}
        initialIndex={1}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <AntApp><DataAnnotationPage /><LocationProbe /><BrowserBackButton /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.change(await screen.findByLabelText("选择模型"), { target: { value: "model-1" } });
    fireEvent.click(await screen.findByRole("button", { name: /下一页/ }));
    fireEvent.click(screen.getByRole("button", { name: "开始自动标注" }));
    await waitFor(() => expect(screen.getByTestId("annotation-location")).toHaveTextContent("runId=run-created"));

    fireEvent.click(screen.getByRole("button", { name: "browser-back" }));

    await waitFor(() => expect(screen.getByTestId("annotation-location")).toHaveTextContent("/data-annotation?view=tasks"));
  });

  it("clusters before configuring typed weak-supervision rules", async () => {
    post.mockImplementation((url: string) => {
      if (url.endsWith("/cluster-preview")) return Promise.resolve({ data: {
        model_id: "model-1",
        feature_count: 1,
        best_k: 2,
        silhouette_scores: { "2": 0.81 },
        cluster_counts: { "0": 10, "1": 2 },
        cluster_summaries: [
          { cluster_id: 0, role: "normal", count: 10, percentage: 83.3 },
          { cluster_id: 1, role: "anomaly", count: 2, percentage: 16.7 },
        ],
        cluster_ids: [0, 0, 1],
        pca_coordinates: [[0, 0], [1, 1], [2, 2]],
        weights: [1],
      } });
      if (url.endsWith("/validate")) return Promise.resolve({ data: { valid_rows: 12, errors: [] } });
      if (url.endsWith("/runs")) return Promise.resolve({ data: { id: "run-weak", status: "queued" } });
      return Promise.resolve({ data: {} });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=setup&mode=automatic&projectId=project-1&datasetId=dataset-report"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.change(await screen.findByLabelText("选择模型"), { target: { value: "model-1" } });
    const nextButton = await screen.findByRole("button", { name: /下一页/ });
    await waitFor(() => expect(nextButton).not.toBeDisabled());
    fireEvent.click(nextButton);
    fireEvent.click(await screen.findByRole("checkbox", { name: "弱监督标注策略" }));
    expect(screen.getByText("已启用")).toBeInTheDocument();
    expect(screen.queryByLabelText("标注规则列表")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始自动标注" })).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "开始聚类" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/cluster-preview",
      { dataset_artifact_id: "dataset-report", selected_model_id: "model-1" },
    ));
    const normalCluster = await screen.findByText("簇0（正常模式）：10条（83.3%）");
    const anomalyCluster = screen.getByText("簇1（异常模式）：2条（16.7%）");
    expect((normalCluster.previousElementSibling as HTMLElement).style.getPropertyValue("--cluster-color")).toBe("#1677ff");
    expect((anomalyCluster.previousElementSibling as HTMLElement).style.getPropertyValue("--cluster-color")).toBe("#d4380d");
    expect(screen.getByLabelText("聚类图像")).toBeInTheDocument();
    expect(screen.getByLabelText("标注规则列表")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("标签数据类型"), { target: { value: "int" } });
    fireEvent.change(screen.getByLabelText("规则 rule-1 条件 1 值"), { target: { value: "wld1c" } });
    expect(screen.queryByLabelText("规则 rule-1 条件 1 类型")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "编辑条件 1：wld1c" })).toHaveTextContent("wld1c");
    fireEvent.change(screen.getByLabelText("规则 rule-1 条件 3 值"), { target: { value: "5" } });
    expect(screen.queryByLabelText("规则 rule-1 条件 3 类型")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "编辑条件 3：5" })).toHaveTextContent("5");
    fireEvent.click(screen.getByRole("button", { name: "编辑条件 1：wld1c" }));
    expect(screen.getByLabelText("规则 rule-1 条件 1 类型")).toHaveValue("data");
    fireEvent.change(screen.getByLabelText("规则 rule-1 条件 1 值"), { target: { value: "wld1c" } });
    fireEvent.change(screen.getByLabelText("规则 rule-1 标签"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "添加条件" }));
    expect(screen.getByRole("button", { name: "删除条件 4" })).toHaveTextContent("×");
    fireEvent.click(screen.getByRole("button", { name: "删除条件 4" }));
    expect(screen.queryByRole("button", { name: "删除条件 4" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "添加一行" }));
    expect(screen.getAllByRole("button", { name: "删除" })).toHaveLength(3);
    fireEvent.click(screen.getAllByRole("button", { name: "删除" })[2]);
    fireEvent.click(screen.getAllByRole("button", { name: "删除" })[1]);

    fireEvent.click(screen.getByRole("button", { name: "开始自动标注" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/validate",
      expect.objectContaining({
        selected_model_id: "model-1",
        label_dtype: "int",
        weak_supervision: true,
        cluster_labels: { "0": "normal", "1": "anomaly" },
        process_rules: [{
          id: "rule-1",
          kind: "condition",
          label: "1",
          tokens: [
            { kind: "data", value: "wld1c" },
            { kind: "logical_operator", value: ">" },
            { kind: "number", value: "5" },
          ],
        }],
      }),
    ));
  });

  it("adds an editable removable fallback rule when weak supervision is enabled", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "通用数据项目", project_role: "owner" }] } });
      if (url.includes("/spot-weld/models")) return Promise.resolve({ data: { items: [{ id: "model-1", name: "通用模型", label_dtype: "string" }] } });
      if (url.includes("/spot-weld/datasets") && url.endsWith("/columns")) return Promise.resolve({ data: { columns: [{ name: "temperature", dtype: "float64" }], row_count: 2 } });
      return Promise.resolve({ data: { items: [] } });
    });
    post.mockImplementation((url: string) => {
      if (url.endsWith("/cluster-preview")) return Promise.resolve({ data: { best_k: 2, feature_count: 1, cluster_summaries: [{ cluster_id: 0, role: "normal", count: 1, percentage: 50 }, { cluster_id: 1, role: "anomaly", count: 1, percentage: 50 }] } });
      if (url.endsWith("/validate")) return Promise.resolve({ data: { valid_rows: 2, errors: [] } });
      if (url.endsWith("/runs")) return Promise.resolve({ data: { id: "run-fallback", project_id: "project-1", status: "queued" } });
      return Promise.resolve({ data: {} });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?view=setup&projectId=project-1&mode=automatic"]}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );
    fireEvent.change(await screen.findByLabelText("数据管理文件"), { target: { value: "dataset-report" } });
    fireEvent.change(screen.getByLabelText("选择模型"), { target: { value: "model-1" } });
    const nextButton = await screen.findByRole("button", { name: /下一页/ });
    await waitFor(() => expect(nextButton).not.toBeDisabled());
    fireEvent.click(nextButton);
    fireEvent.click(await screen.findByRole("checkbox", { name: "弱监督标注策略" }));
    fireEvent.click(await screen.findByRole("button", { name: "开始聚类" }));
    expect(await screen.findByDisplayValue("其他")).toBeInTheDocument();
    expect(screen.getByText("除以上规则之外")).toBeInTheDocument();
    expect(screen.queryByLabelText(/fallback-rule 条件 1 类型/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "弱监督标注策略" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "弱监督标注策略" }));
    fireEvent.click(await screen.findByRole("button", { name: "开始聚类" }));
    expect(await screen.findAllByDisplayValue("其他")).toHaveLength(1);

    fireEvent.change(screen.getByDisplayValue("其他"), { target: { value: "未分类" } });
    fireEvent.click(screen.getAllByRole("button", { name: "删除" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "开始自动标注" }));

    const expectedFallbackRule = {
      id: expect.stringMatching(/^fallback-rule-/),
      kind: "fallback",
      label: "未分类",
      tokens: [],
    };
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/validate",
      expect.objectContaining({ process_rules: [expectedFallbackRule] }),
    ));
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs",
      expect.objectContaining({ process_rules: [expectedFallbackRule] }),
    ));
  });

  it("creates a manual task from its dedicated entry with a new target column", async () => {
    post.mockImplementation((url: string) => {
      if (url.endsWith("/spot-weld/validate")) return Promise.resolve({ data: { valid_rows: 12, errors: [] } });
      if (url.endsWith("/spot-weld/runs")) return Promise.resolve({ data: { id: "run-manual", status: "queued" } });
      return Promise.resolve({ data: {} });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=setup&mode=manual&projectId=project-1&datasetId=dataset-report"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "新建手动标注任务" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("目标列来源"), { target: { value: "new" } });
    fireEvent.change(screen.getByLabelText("数据类型"), { target: { value: "float" } });
    fireEvent.change(screen.getByLabelText("目标列"), { target: { value: "人工标签" } });
    fireEvent.click(screen.getByRole("button", { name: "开始手动标注" }));

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs",
      {
        dataset_artifact_id: "dataset-report",
        field_mapping: {},
        algorithm_ids: [],
        search_method: "bayesian",
        max_trials: 20,
        time_budget: 600,
        label_mode: "manual",
        workflow_kind: "data_annotation",
        target_column: "人工标签",
        target_column_created: true,
        target_column_dtype: "float",
        input_columns: ["wld1c", "Fault"],
      },
    ));
  });

  it("uses an existing target column's dtype and values as manual label options", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "焊装线", project_role: "owner" }] } });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [{
        id: "run-manual", status: "completed", label_mode: "manual",
        target_schema: { name: "Fault", dtype: "int64", classes: ["0", "1"] },
      }] } });
      if (url.endsWith("/samples")) return Promise.resolve({ data: { items: [{ id: "sample-1", display_id: "W-0001", review_status: "pending_review", warning_level: "critical" }] } });
      if (url.endsWith("/samples/sample-1")) return Promise.resolve({ data: {
        id: "sample-1", display_id: "W-0001", review_status: "pending_review",
        waveforms: { current: [1], voltage: [2], resistance: [3], power: [4] },
      } });
      return Promise.resolve({ data: { items: [] } });
    });
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-manual"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "W-0001" }));

    expect(await screen.findByRole("heading", { name: "人工标签（Fault · int64）" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "0" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "正常" })).not.toBeInTheDocument();
    const manualQueueTag = within(screen.getByRole("button", { name: "W-0001" })).getByText("-");
    expect(manualQueueTag).not.toHaveClass("ant-tag-red");
    fireEvent.click(screen.getByRole("button", { name: "1" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs/run-manual/samples/sample-1/labels",
      { label: "1", note: "" },
    ));
  });

  it("normalizes a newly added numeric label before submitting it", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "焊装线", project_role: "owner" }] } });
      if (url === "/projects/project-1/spot-weld/runs") return Promise.resolve({ data: { items: [{ id: "run-manual", status: "completed", label_mode: "manual", target_schema: { name: "Fault", dtype: "int64", classes: ["0", "1"] } }] } });
      if (url.endsWith("/samples")) return Promise.resolve({ data: { items: [{ id: "sample-1", display_id: "W-0001", review_status: "pending_review" }] } });
      if (url.endsWith("/samples/sample-1")) return Promise.resolve({ data: { id: "sample-1", display_id: "W-0001", review_status: "pending_review", waveforms: { current: [], voltage: [], resistance: [], power: [] } } });
      return Promise.resolve({ data: { items: [] } });
    });
    render(<MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-manual"]}><AntApp><DataAnnotationPage /></AntApp></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "W-0001" }));
    fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
    fireEvent.change(screen.getByRole("textbox", { name: "新建人工标签" }), { target: { value: "2.0" } });
    fireEvent.click(screen.getByRole("button", { name: "添加标签" }));
    expect(screen.getByRole("button", { name: "2" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/projects/project-1/spot-weld/runs/run-manual/samples/sample-1/labels",
      { label: "2", note: "" },
    ));
  });

  it("does not render the removed label-training controls", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "W-0001" }));
    expect(screen.queryByText("审核标签训练")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "训练快照" })).not.toBeInTheDocument();
  });

  it("keeps label changes in the detail page instead of snapshot controls", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&projectId=project-1&runId=run-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "W-0001" }));
    expect(await screen.findByRole("button", { name: "0" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByLabelText("快照名称")).not.toBeInTheDocument();
  });

  it("removes simulation and mode-switch controls from task creation", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=setup&projectId=project-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "新建自动标注任务" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /模拟数据/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "自动标注" })).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "手动标注" })).not.toBeInTheDocument();
  });
});
