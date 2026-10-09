import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NotebookPage from "./NotebookPage";
import type { ContainerImage, NotebookSession } from "../api/notebooks";

const mocks = vi.hoisted(() => ({
  listNotebooks: vi.fn(),
  startNotebook: vi.fn(),
  stopNotebook: vi.fn(),
  reconcileNotebook: vi.fn(),
  openNotebook: vi.fn(),
  listImages: vi.fn(),
  registerImage: vi.fn(),
  updateImage: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/notebooks", () => mocks);
vi.mock("../api/client", () => ({
  default: { get: vi.fn().mockResolvedValue({ data: { items: [{ id: "c1", name: "w15-cluster" }] } }) },
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      notebooks: {
        title: "Notebook 会话", refresh: "刷新", start: "启动会话", empty: "暂无会话",
        status: "状态", jobName: "会话", image: "镜像", namespace: "命名空间", idle: "空闲回收(秒)",
        cluster: "集群", actions: "操作", open: "打开", stop: "停止", loadFailed: "加载失败",
        startOk: "会话已启动", startFailed: "启动失败", startOkButton: "启动", stopOk: "已停止",
        stopFailed: "停止失败", openFailed: "打开失败", cancel: "取消",
      },
      common: { cancel: "取消" },
    },
  }),
}));

function makeSession(overrides: Partial<NotebookSession> = {}): NotebookSession {
  return {
    id: "nb-1",
    project_id: "p1",
    user_id: "u1",
    cluster_id: "c1",
    namespace: "w15-notebooks",
    job_name: "lr-notebook-aaaa-1",
    image_ref: "registry.local/w15/base@sha256:" + "b".repeat(64),
    resource_json: {},
    status: "running",
    idle_timeout_seconds: 3600,
    error_code: null,
    last_activity_at: null,
    started_at: null,
    terminated_at: null,
    created_at: null,
    ...overrides,
  };
}

const makeImage = (overrides: Partial<ContainerImage> = {}): ContainerImage => ({
  id: "img-1",
  project_id: "p1",
  registry: "registry.local",
  repository: "w15/base",
  digest: "sha256:" + "b".repeat(64),
  visibility: "project",
  scan_status: "passed",
  scan_report_ref: null,
  source: "manual_registry",
  description: null,
  created_at: null,
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listNotebooks.mockResolvedValue({ items: [], total: 0 });
  mocks.listImages.mockResolvedValue({ items: [makeImage()], total: 1 });
});

describe("NotebookPage", () => {
  it("renders sessions with status and image digest", async () => {
    mocks.listNotebooks.mockResolvedValue({ items: [makeSession()], total: 1 });
    render(
      <AntApp>
        <NotebookPage />
      </AntApp>,
    );
    expect(await screen.findByText("lr-notebook-aaaa-1")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
  });

  it("offers only scan-passed catalog images in the start form", async () => {
    mocks.listImages.mockResolvedValue({
      items: [makeImage(), makeImage({ id: "img-2", repository: "w15/bad", scan_status: "failed" })],
      total: 2,
    });
    render(
      <AntApp>
        <NotebookPage />
      </AntApp>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /启动会话/ }));
    // Open the image select dropdown (antd renders options lazily). Combos:
    // 0=cluster 1=namespace 2=image.
    fireEvent.mouseDown(screen.getAllByRole("combobox")[2]);
    const options = await screen.findAllByText(/registry\.local\/w15\/base@sha256/);
    expect(options.length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/w15\/bad/)).not.toBeInTheDocument();
  });

  it("stops a running session and reloads", async () => {
    const session = makeSession();
    mocks.listNotebooks.mockResolvedValue({ items: [session], total: 1 });
    mocks.stopNotebook.mockResolvedValue({ ...session, status: "stopped" });
    render(
      <AntApp>
        <NotebookPage />
      </AntApp>,
    );
    const row = await screen.findByText("lr-notebook-aaaa-1").then((node) => node.closest("tr")!);
    fireEvent.click(row.querySelector("button.ant-btn-dangerous")!);
    await waitFor(() => expect(mocks.stopNotebook).toHaveBeenCalledWith("nb-1"));
    await waitFor(() => expect(mocks.listNotebooks).toHaveBeenCalledTimes(2));
  });

  it("disables stop for terminal sessions", async () => {
    const stopped = makeSession({ status: "stopped" });
    mocks.listNotebooks.mockResolvedValue({ items: [stopped], total: 1 });
    render(
      <AntApp>
        <NotebookPage />
      </AntApp>,
    );
    const row = await screen.findByText("lr-notebook-aaaa-1").then((node) => node.closest("tr")!);
    const stop = Array.from(row.querySelectorAll("button")).find((b) => b.textContent === "停止") as HTMLButtonElement;
    expect(stop).toBeDisabled();
  });
});
