import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import JobRunsPage from "./JobRunsPage";
import type { JobRun } from "../api/kubernetesJobs";

const mocks = vi.hoisted(() => ({
  listJobRuns: vi.fn(),
  getJobRun: vi.fn(),
  cancelJobRun: vi.fn(),
  reconcileJobRun: vi.fn(),
  getJobRunLogs: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/kubernetesJobs", () => mocks);
vi.mock("../api/client", () => ({
  default: { get: vi.fn(), post: vi.fn() },
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      jobRuns: {
        title: "作业运行", refresh: "刷新", empty: "暂无作业", status: "状态",
        jobName: "作业名", image: "镜像", namespace: "命名空间", revision: "代次",
        timeout: "超时(秒)", progress: "执行进度", actions: "操作", logs: "日志",
        cancel: "取消", cancelDisabled: "终态作业不可取消", reconcile: "对账",
        loadFailed: "加载失败", loadMore: "加载更多", endOfStream: "已到日志末尾",
        logTitle: "作业日志", cancelOk: "已请求取消", cancelFailed: "取消失败",
        reconcileOk: "对账完成", reconcileFailed: "对账失败", logFailed: "日志加载失败",
        cancelReason: "user cancelled from console",
        timeoutHint: "作业超过 activeDeadline 期限,已按超时终态收口。",
        orphanedHint: "集群内找不到对应 Job 资源,作业按 orphaned 终态收口。",
      },
      common: { cancel: "取消" },
    },
  }),
}));

function renderPage() {
  return render(
    <AntApp>
      <JobRunsPage />
    </AntApp>,
  );
}

let jobSeq = 0;

function makeJob(overrides: Partial<JobRun> = {}): JobRun {
  jobSeq += 1;
  return {
    id: `job-${jobSeq}`,
    project_id: "p1",
    cluster_id: "c1",
    namespace: "w14-jobs",
    job_name: `lr-aaaaaaaa-job-bbbbbbbb-${jobSeq}`,
    image_ref: "registry.local/w14-demo@sha256:" + "a".repeat(64),
    command_json: ["/bin/sh", "-c"],
    args_json: ["echo w14"],
    resource_json: { cpu_cores: 1, memory_gb: 1 },
    status: "running",
    status_detail: null,
    error_code: null,
    revision: 1,
    timeout_seconds: 120,
    exit_code: null,
    submitted_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    finished_at: null,
    created_at: new Date().toISOString(),
    operation_state: "running",
    operation_progress: 40,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  jobSeq = 0;
  mocks.listJobRuns.mockResolvedValue({ items: [], total: 0 });
  mocks.getJobRunLogs.mockResolvedValue({ text: "", next_cursor: 0, end_of_stream: true });
});

describe("JobRunsPage", () => {
  it("renders job rows with status badge and operation stage/progress", async () => {
    mocks.listJobRuns.mockResolvedValue({ items: [makeJob()], total: 1 });
    renderPage();
    expect(await screen.findByText("lr-aaaaaaaa-job-bbbbbbbb-1")).toBeInTheDocument();
    // Status badge and the durable operation stage both read "running".
    expect(screen.getAllByText("running").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("40%")).toBeInTheDocument();
  });

  it("disables cancel for terminal jobs and keeps it enabled while running", async () => {
    const running = makeJob();
    const done = makeJob({ status: "succeeded", exit_code: 0, operation_progress: 100 });
    mocks.listJobRuns.mockResolvedValue({ items: [running, done], total: 2 });
    renderPage();
    const runningRow = await screen
      .findByText("lr-aaaaaaaa-job-bbbbbbbb-1")
      .then((node) => node.closest("tr")!);
    const doneRow = await screen
      .findByText("lr-aaaaaaaa-job-bbbbbbbb-2")
      .then((node) => node.closest("tr")!);
    const runningCancel = Array.from(runningRow.querySelectorAll("button")).find(
      (button) => button.textContent === "取消",
    ) as HTMLButtonElement;
    expect(runningCancel).not.toBeDisabled();
    const doneCancel = Array.from(doneRow.querySelectorAll("button")).find(
      (button) => button.textContent === "取消",
    ) as HTMLButtonElement;
    expect(doneCancel).toBeDisabled();
    expect(screen.getAllByTestId("cancel-disabled-hint").length).toBeGreaterThanOrEqual(1);
  });

  it("loads logs incrementally by cursor and surfaces end_of_stream", async () => {
    const job = makeJob();
    mocks.listJobRuns.mockResolvedValue({ items: [job], total: 1 });
    mocks.getJobRunLogs
      .mockResolvedValueOnce({ text: "chunk-1\n", next_cursor: 8, end_of_stream: false })
      .mockResolvedValueOnce({ text: "chunk-2\n", next_cursor: 16, end_of_stream: true });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /日志/ }));
    expect(await screen.findByText(/chunk-1/)).toBeInTheDocument();
    expect(mocks.getJobRunLogs).toHaveBeenCalledWith(job.id, 0);

    const more = screen.getByRole("button", { name: /加载更多/ });
    expect(more).not.toBeDisabled();
    fireEvent.click(more);
    await waitFor(() => expect(mocks.getJobRunLogs).toHaveBeenCalledWith(job.id, 8));
    expect(await screen.findByText(/chunk-2/)).toBeInTheDocument();
    expect(screen.getByTestId("end-of-stream")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /加载更多/ })).toBeDisabled());
  });

  it("explains timed_out and orphaned terminal states", async () => {
    const timedOut = makeJob({ status: "timed_out", error_code: "KUBE_JOB_TIMEOUT" });
    const orphaned = makeJob({ status: "orphaned", error_code: "KUBE_JOB_ORPHANED" });
    mocks.listJobRuns.mockResolvedValue({ items: [timedOut, orphaned], total: 2 });
    renderPage();
    expect(await screen.findByTestId(`hint-${timedOut.id}`)).toHaveTextContent("activeDeadline");
    expect(await screen.findByTestId(`hint-${orphaned.id}`)).toHaveTextContent("orphaned");
  });

  it("cancels a running job and reloads the list", async () => {
    const job = makeJob();
    mocks.listJobRuns.mockResolvedValue({ items: [job], total: 1 });
    mocks.cancelJobRun.mockResolvedValue({ ...job, status: "cancelled" });
    renderPage();
    const row = await screen.findByText("lr-aaaaaaaa-job-bbbbbbbb-1").then((node) => node.closest("tr")!);
    const cancel = Array.from(row.querySelectorAll("button")).find(
      (button) => button.textContent === "取消",
    ) as HTMLButtonElement;
    fireEvent.click(cancel);
    await waitFor(() => expect(mocks.cancelJobRun).toHaveBeenCalledWith(job.id, "user cancelled from console"));
    await waitFor(() => expect(mocks.listJobRuns).toHaveBeenCalledTimes(2));
  });

  it("reconciles a job on demand", async () => {
    const job = makeJob();
    mocks.listJobRuns.mockResolvedValue({ items: [job], total: 1 });
    mocks.reconcileJobRun.mockResolvedValue(job);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /对账/ }));
    await waitFor(() => expect(mocks.reconcileJobRun).toHaveBeenCalledWith(job.id));
    await waitFor(() => expect(mocks.listJobRuns).toHaveBeenCalledTimes(2));
  });
});
