/** 动作审计页测试（S1/R5）：筛选/表格/链校验卡两态/CSV 按钮。 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App as AntApp } from "antd";
import { LangProvider } from "../i18n";
import AgentActionAuditPage from "./AgentActionAuditPage";

const apiMocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("../api/client", () => ({ default: apiMocks }));
vi.mock("../api/qualityAlerts", () => ({ apiErrorText: (e: unknown) => String(e) }));

const ROW = {
  id: "row-1",
  created_at: "2026-11-26T10:00:00",
  agent_type: "chat",
  tool_name: "chat",
  status: "success",
  error_code: null,
  duration_ms: 120,
  project_id: "p-1",
  trace_id: "tr-1",
  idempotency_key: null,
  repeat_count: 0,
  usage: { total_tokens: 42 },
  model_profile: "deepseek-chat",
  request_payload: { messages: [{ role: "user", content: "看趋势" }] },
  response_payload: { reply: "好的" },
};

function renderPage() {
  return render(
    <MemoryRouter>
      <LangProvider>
        <AntApp>
          <AgentActionAuditPage />
        </AntApp>
      </LangProvider>
    </MemoryRouter>,
  );
}

describe("AgentActionAuditPage", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "zh");
    apiMocks.get.mockReset();
    apiMocks.get.mockImplementation((url: string) => {
      if (url === "/admin/agent-actions") {
        return Promise.resolve({ data: { items: [ROW], total: 1 } });
      }
      if (url === "/admin/audit-chain/verify") {
        return Promise.resolve({
          data: {
            audit_events: { chained: 5, unchained: 2, complete: true, first_break: null },
            platform_audit_events: { chained: 3, unchained: 0, complete: false, first_break: { seq: 2, id: "x", reason: "hash_mismatch" } },
          },
        });
      }
      return Promise.resolve({ data: {} });
    });
  });

  it("renders rows with usage and profile columns", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("deepseek-chat")).toBeTruthy());
    expect(screen.getByText("42 tok")).toBeTruthy();
  });

  it("verify chain reports both tables and locates the break", async () => {
    renderPage();
    await waitFor(() => screen.getByTestId("verify-chain"));
    fireEvent.click(screen.getByTestId("verify-chain"));
    await waitFor(() => expect(screen.getByTestId("chain-result")).toBeTruthy());
    expect(screen.getByText("audit_events")).toBeTruthy();
    expect(screen.getByText("platform_audit_events")).toBeTruthy();
    expect(screen.getByText(/seq=2/)).toBeTruthy();
    expect(screen.getByText(/hash_mismatch/)).toBeTruthy();
  });

  it("export button triggers csv download request", async () => {
    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();
    renderPage();
    await waitFor(() => screen.getByText("导出 CSV"));
    apiMocks.get.mockResolvedValueOnce({ data: new Blob(["a,b"]) });
    fireEvent.click(screen.getByText("导出 CSV"));
    await waitFor(() =>
      expect(apiMocks.get).toHaveBeenCalledWith(
        "/admin/agent-actions/export.csv",
        { responseType: "blob" },
      ),
    );
  });
});
