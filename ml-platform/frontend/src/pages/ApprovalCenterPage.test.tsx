/** 审批中心页测试（S1/R5）：两页签渲染、批准/驳回流程、驳回强制备注。 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App as AntApp } from "antd";
import { LangProvider } from "../i18n";
import ApprovalCenterPage from "./ApprovalCenterPage";

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("../api/client", () => ({ default: apiMocks }));
vi.mock("../api/qualityAlerts", () => ({
  apiErrorText: (e: unknown) => String(e),
}));

const APPROVAL = {
  id: "ap-1",
  project_id: "p-1",
  type: "retrain_proposal",
  title: "重训提案：漂移报告 a1b2（severe）",
  payload: {},
  status: "pending",
  decision_note: null,
  created_by_id: "u-owner",
  decided_by_id: null,
  decided_at: null,
  expires_at: new Date(Date.now() + 3600_000).toISOString(),
  reminded_at: null,
  execution_status: "none",
  execution_ref: null,
  execution_error: null,
  trace_id: "t-1",
  created_at: new Date().toISOString(),
  can_approve: true,
};

function baseRouter(url = "/approvals") {
  apiMocks.get.mockImplementation((url: string) => {
    if (url === "/projects") {
      return Promise.resolve({ data: { items: [{ id: "p-1", name: "点焊项目" }] } });
    }
    if (url === "/approvals/pending-count") {
      return Promise.resolve({ data: { count: 1 } });
    }
    if (url.includes("/approvals/legacy")) {
      return Promise.resolve({
        data: {
          items: [
            {
              source: "model_version", ref_id: "v-1", title: "模型版本 v7",
              raw_status: "pending", status: "pending", initiator: "u-owner",
              decided_at: null, link: "/models", note: null,
            },
          ],
        },
      });
    }
    if (url.includes("/approvals") && !url.includes("legacy") && !url.includes("pending-count")) {
      return Promise.resolve({ data: { items: [APPROVAL], total: 1 } });
    }
    return Promise.resolve({ data: {} });
  });
}

function renderPage(url = "/approvals") {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <LangProvider>
        <AntApp>
          <ApprovalCenterPage />
        </AntApp>
      </LangProvider>
    </MemoryRouter>,
  );
}

describe("ApprovalCenterPage", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    apiMocks.get.mockReset();
    apiMocks.post.mockReset();
    baseRouter();
  });

  it("renders queue tab with approval row and four-eyes hint", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("重训提案：漂移报告 a1b2（severe）")).toBeTruthy());
    expect(screen.getByText("四眼原则：审批人与发起人必须不同；72h 未处理自动过期回收")).toBeTruthy();
    expect(screen.getByTestId("approve-ap-1")).toBeTruthy();
    expect(screen.getByTestId("reject-ap-1")).toBeTruthy();
  });

  it("reject requires a note and posts it", async () => {
    renderPage();
    await waitFor(() => screen.getByTestId("reject-ap-1"));
    fireEvent.click(screen.getByTestId("reject-ap-1"));
    const dialog = await screen.findByRole("dialog");
    const okButton = await within(dialog).findByRole("button", { name: /驳\s*回/ });
    fireEvent.click(okButton);
    await waitFor(() => expect(screen.getAllByText("驳回意见（必填）").length).toBeGreaterThan(0));
    fireEvent.change(await screen.findByLabelText("驳回意见"), {
      target: { value: "证据不足" },
    });
    apiMocks.post.mockResolvedValueOnce({ data: { ...APPROVAL, status: "rejected" } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /驳\s*回/ }));
    await waitFor(() =>
      expect(apiMocks.post).toHaveBeenCalledWith(
        "/projects/p-1/approvals/ap-1/reject",
        { note: "证据不足" },
      ),
    );
  });

  it("approve posts without note", async () => {
    renderPage();
    await waitFor(() => screen.getByTestId("approve-ap-1"));
    apiMocks.post.mockResolvedValueOnce({ data: { ...APPROVAL, status: "approved" } });
    fireEvent.click(screen.getByTestId("approve-ap-1"));
    await waitFor(() =>
      expect(apiMocks.post).toHaveBeenCalledWith("/projects/p-1/approvals/ap-1/approve", { note: null }),
    );
  });

  it("legacy tab shows four sources with mapped status", async () => {
    renderPage();
    await waitFor(() => screen.getByText("存量审批"));
    fireEvent.click(screen.getByText("存量审批"));
    await waitFor(() => expect(screen.getByText("模型版本（存量）")).toBeTruthy());
    expect(screen.getByText("模型版本 v7")).toBeTruthy();
  });
});
