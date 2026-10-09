import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ImageCatalogPage from "./ImageCatalogPage";
import type { ContainerImage } from "../api/notebooks";

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
  default: { get: vi.fn() },
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      images: {
        title: "镜像目录", refresh: "刷新", register: "登记镜像", empty: "目录为空",
        repository: "仓库路径", registry: "Registry", digest: "摘要(sha256,不可变)",
        digestPattern: "格式:sha256:64 位十六进制", scan: "扫描", visibility: "可见性",
        source: "来源", actions: "操作", loadFailed: "加载失败", registerOk: "镜像已登记",
        registerFailed: "登记失败", updateFailed: "更新失败", save: "保存", cancel: "取消",
      },
      common: { cancel: "取消" },
    },
  }),
}));

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
  mocks.listImages.mockResolvedValue({ items: [makeImage()], total: 1 });
});

describe("ImageCatalogPage", () => {
  it("renders catalog entries with short digest and scan badge", async () => {
    render(
      <AntApp>
        <ImageCatalogPage />
      </AntApp>,
    );
    expect(await screen.findByText("registry.local/w15/base")).toBeInTheDocument();
    const digestCell = screen.getByTitle("sha256:" + "b".repeat(64));
    expect(digestCell.textContent).toMatch(/^sha256:bbbbbbb…bbbbbb$/);
    expect(screen.getAllByRole("combobox").length).toBeGreaterThanOrEqual(1);
  });

  it("registers an image through the form", async () => {
    mocks.registerImage.mockResolvedValue(makeImage());
    render(
      <AntApp>
        <ImageCatalogPage />
      </AntApp>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /登记镜像/ }));
    fireEvent.change(screen.getByPlaceholderText("registry.local"), { target: { value: "registry.local" } });
    fireEvent.change(screen.getByPlaceholderText("w15/notebook-base"), { target: { value: "w15/new" } });
    fireEvent.change(screen.getByPlaceholderText("sha256:…"), { target: { value: "sha256:" + "f".repeat(64) } });
    fireEvent.click(screen.getByRole("button", { name: /保\s*存/ }));
    await waitFor(() =>
      expect(mocks.registerImage).toHaveBeenCalledWith(
        expect.objectContaining({ registry: "registry.local", repository: "w15/new" }),
      ),
    );
    await waitFor(() => expect(mocks.listImages).toHaveBeenCalledTimes(2));
  });

  it("rejects malformed digest in the register form", async () => {
    render(
      <AntApp>
        <ImageCatalogPage />
      </AntApp>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /登记镜像/ }));
    fireEvent.change(screen.getByPlaceholderText("registry.local"), { target: { value: "registry.local" } });
    fireEvent.change(screen.getByPlaceholderText("w15/notebook-base"), { target: { value: "w15/new" } });
    fireEvent.change(screen.getByPlaceholderText("sha256:…"), { target: { value: "sha256:short" } });
    fireEvent.click(screen.getByRole("button", { name: /保\s*存/ }));
    await waitFor(() => expect(screen.getByText("格式:sha256:64 位十六进制")).toBeInTheDocument());
    expect(mocks.registerImage).not.toHaveBeenCalled();
  });

  it("updates scan status from the row selector", async () => {
    mocks.updateImage.mockResolvedValue(makeImage());
    render(
      <AntApp>
        <ImageCatalogPage />
      </AntApp>,
    );
    const combo = await screen.findByRole("combobox");
    fireEvent.mouseDown(combo);
    fireEvent.click(await screen.findByText("failed"));
    await waitFor(() => expect(mocks.updateImage).toHaveBeenCalledWith("img-1", { scan_status: "failed" }));
  });
});
