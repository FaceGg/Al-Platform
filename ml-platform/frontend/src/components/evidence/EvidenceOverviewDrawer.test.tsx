import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { LangProvider } from "../../i18n";
import { ThemeProvider } from "../../stores/themeContext";
import { App as AntApp } from "antd";

const mocks = vi.hoisted(() => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

// 组件在 components/evidence/ 下：相对路径要多上一层
vi.mock("../../api/client", () => ({
  default: mocks.apiClient,
  formatApiError: vi.fn((_e: unknown, fallback: string) => fallback),
}));

import EvidenceOverviewDrawer from "./EvidenceOverviewDrawer";

function stage(key: string, title: string, status: string, note: string, evidence: unknown[] = []) {
  return { key, title, title_en: title, status, note, evidence };
}

const OVERVIEW = {
  model_version: {
    id: "v1", version_number: 1, model_name: "点焊模型", source_kind: "platform_joblib",
    algorithm: "logistic_regression", framework: "sklearn", approval_status: "approved",
    lifecycle_state: "approved", training_job_id: "j1", dataset_version_id: "dv1",
  },
  stages: [
    stage("ingest", "接入", "complete", "数据集版本 v2：500 行", [
      { label: "数据集版本 v2", ref_type: "dataset_version", ref_id: "dv1" },
      { label: "数据集工件", ref_type: "artifact", ref_id: "a1" },
    ]),
    stage("split", "切分", "not_supported", "平台尚无数据集划分管理（随第二批接入）"),
    stage("production", "推送生产", "pending", "该版本尚未部署到生产"),
  ],
  checks: [
    { key: "model_file", title: "模型文件", title_en: "Model file", status: "pass", detail: "工件 model.joblib" },
    { key: "checksum", title: "校验和", title_en: "Checksum", status: "pass", detail: "工件登记了 SHA-256（总览不重算文件哈希）" },
    { key: "production_unique", title: "生产版本唯一", title_en: "Single production version", status: "fail", detail: "同一模型下有 2 个版本同时在生产" },
  ],
  summary: { complete: 1, pending: 1, missing: 0, not_supported: 1, not_applicable: 0 },
  checks_passed: 2,
  checksum_verified: false,
  generated_at: "2026-11-26T10:00:00",
  archived_check: null,
};

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}</div>;
}

function renderDrawer(props: Partial<React.ComponentProps<typeof EvidenceOverviewDrawer>> = {}) {
  const onClose = vi.fn();
  render(
    <MemoryRouter>
      <LangProvider><ThemeProvider><AntApp>
        <EvidenceOverviewDrawer projectId="p1" versionId="v1" label="v1" onClose={onClose} {...props} />
        <LocationProbe />
      </AntApp></ThemeProvider></LangProvider>
    </MemoryRouter>,
  );
  return { onClose };
}

describe("EvidenceOverviewDrawer（闭环证据总览）", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    vi.clearAllMocks();
    mocks.apiClient.get.mockImplementation((url: string) => {
      if (url === "/projects/p1/model-versions/v1/evidence-overview") return Promise.resolve({ data: OVERVIEW });
      if (url.endsWith("/download")) return Promise.resolve({ data: new Blob(["zip"]) });
      return Promise.resolve({ data: {} });
    });
    mocks.apiClient.post.mockResolvedValue({ data: { ...OVERVIEW, checksum_verified: true, archived_check_id: "c1" } });
    URL.createObjectURL = vi.fn(() => "blob:demo");
    URL.revokeObjectURL = vi.fn();
  });

  it("shows stage statuses honestly and the launch check tally", async () => {
    renderDrawer();
    const overview = await screen.findByTestId("evidence-overview");
    expect(screen.getByTestId("stage-status-ingest")).toHaveTextContent("完成");
    expect(screen.getByTestId("stage-status-split")).toHaveTextContent("未接入");
    expect(screen.getByTestId("stage-status-production")).toHaveTextContent("待发生");
    // 「未接入」与「缺失」在页面上有明确区分说明
    expect(screen.getByTestId("evidence-stage-footnote")).toHaveTextContent("不代表该模型缺证据");
    expect(screen.getByTestId("stage-summary-not_supported")).toHaveTextContent("未接入 × 1");
    expect(screen.getByTestId("evidence-check-summary")).toHaveTextContent("上线检查 2/3 项通过");
    expect(screen.getByTestId("check-status-production_unique")).toHaveTextContent("未通过");
    expect(screen.getByTestId("evidence-check-summary")).toHaveTextContent("总览不重算模型文件哈希");
  });

  it("links only evidence that has a page and navigates on click", async () => {
    renderDrawer();
    await screen.findByTestId("evidence-stages");
    const stages = screen.getByTestId("evidence-stages");
    // 数据集版本有页面 → 可下钻；工件没有页面 → 只展示引用，不给死链
    expect(within(stages).getByRole("button", { name: "打开 数据集版本 v2" })).toBeInTheDocument();
    expect(within(stages).queryByRole("button", { name: "打开 数据集工件" })).not.toBeInTheDocument();
    expect(stages).toHaveTextContent("artifact a1");
    fireEvent.click(within(stages).getByRole("button", { name: "打开 数据集版本 v2" }));
    await waitFor(() => expect(screen.getByTestId("location-probe")).toHaveTextContent("/data"));
  });

  it("archives a check with a recomputed checksum when the user can manage", async () => {
    renderDrawer({ canManage: true });
    await screen.findByTestId("evidence-overview");
    fireEvent.click(screen.getByTestId("evidence-archive"));
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith(
      "/projects/p1/model-versions/v1/evidence-checks",
    ));
    await waitFor(() => expect(screen.getByTestId("evidence-check-summary")).toHaveTextContent("当前结果来自留档"));
  });

  it("hides the archive action for members without manage permission", async () => {
    renderDrawer({ canManage: false });
    await screen.findByTestId("evidence-overview");
    expect(screen.queryByTestId("evidence-archive")).not.toBeInTheDocument();
    expect(screen.getByTestId("evidence-export")).toBeInTheDocument();
  });

  it("exports the evidence package and downloads it", async () => {
    mocks.apiClient.post.mockResolvedValue({
      data: { artifact_id: "e1", name: "evidence.zip", file_size: 10, sha256: "x", file_count: 4, include_audit: false },
    });
    renderDrawer();
    await screen.findByTestId("evidence-overview");
    fireEvent.click(screen.getByTestId("evidence-export"));
    await waitFor(() => expect(mocks.apiClient.post).toHaveBeenCalledWith(
      "/projects/p1/evidence-exports", { scope: "model_version", target_id: "v1" },
    ));
    await waitFor(() => expect(mocks.apiClient.get).toHaveBeenCalledWith(
      "/projects/p1/evidence-exports/e1/download", expect.objectContaining({ responseType: "blob" }),
    ));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());
  });
});
