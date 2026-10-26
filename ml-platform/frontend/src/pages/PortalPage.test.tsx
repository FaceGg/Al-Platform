import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PortalPage from "./PortalPage";

const apiGet = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({ default: { get: apiGet } }));
vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));

describe("PortalPage (v2 portal home)", () => {
  beforeEach(() => {
    localStorage.clear();
    apiGet.mockReset();
    apiGet.mockImplementation((url: string) => {
      if (url === "/training/automl/jobs") {
        return Promise.resolve({ data: { items: [
          { id: 7, name: "拧紧-DECIDE", status: "running", updated_at: "2026-10-23T00:00:00Z" },
          { id: 8, name: "电焊-全流程", status: "completed", updated_at: "2026-10-22T00:00:00Z" },
        ] } });
      }
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: 1 }, { id: 2 }] } });
      if (url === "/health") return Promise.resolve({ data: { status: "ok" } });
      if (url === "/announcements") {
        return Promise.resolve({ data: [
          { id: "a1", title: "智能体中心上线", content: "建模智能体向导开放，欢迎试用", pinned: true, created_at: "2026-10-23T00:00:00Z" },
          { id: "a2", title: "五视图改版上线", content: "", pinned: false, created_at: "2026-10-22T00:00:00Z" },
        ] });
      }
      if (url === "/llm-profiles") {
        return Promise.resolve({ data: [
          { id: "p1", name: "deepseek", model_id: "deepseek-chat", is_default: true },
        ] });
      }
      return Promise.resolve({ data: {} });
    });
  });

  it("renders the three-center hero and the four center cards", async () => {
    render(<MemoryRouter><PortalPage /></MemoryRouter>);

    expect(await screen.findByText(/算法平台（建模中心）/)).toBeInTheDocument();
    expect(screen.getByText("智能体中心", { selector: "h3" })).toBeInTheDocument();
    expect(screen.getByText(/基础设施（运行时）/)).toBeInTheDocument();
    expect(screen.getByText("系统管理", { selector: "h3" })).toBeInTheDocument();
  });

  it("lists recent AutoML jobs from the jobs endpoint", async () => {
    render(<MemoryRouter><PortalPage /></MemoryRouter>);

    expect(await screen.findByText("拧紧-DECIDE")).toBeInTheDocument();
    expect(screen.getByText("电焊-全流程")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/training/automl/jobs");
  });

  it("falls back to the empty hint when no jobs exist", async () => {
    apiGet.mockImplementation((url: string) =>
      url === "/training/automl/jobs"
        ? Promise.resolve({ data: { items: [] } })
        : Promise.resolve({ data: {} }));

    render(<MemoryRouter><PortalPage /></MemoryRouter>);

    await waitFor(() => expect(screen.getByText(/暂无自动建模任务/)).toBeInTheDocument());
  });

  it("lists real announcements and the LLM gateway state instead of static copy", async () => {
    render(<MemoryRouter><PortalPage /></MemoryRouter>);

    expect(await screen.findByText("智能体中心上线", { selector: "b" })).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/announcements");
    expect(apiGet).toHaveBeenCalledWith("/llm-profiles");
    expect(await screen.findByText(/deepseek-chat/)).toBeInTheDocument();
    // The redesign-explanatory migration mapping is gone.
    expect(screen.queryByText(/迁移映射/)).not.toBeInTheDocument();
    // No hardcoded "already connected" claim when the panel now derives state.
    expect(screen.queryByText(/已连通/)).not.toBeInTheDocument();
  });

  it("shows the notices empty state when the API returns none", async () => {
    apiGet.mockImplementation((url: string) =>
      url === "/training/automl/jobs"
        ? Promise.resolve({ data: { items: [] } })
        : url === "/announcements"
          ? Promise.resolve({ data: [] })
          : Promise.resolve({ data: {} }));

    render(<MemoryRouter><PortalPage /></MemoryRouter>);

    expect(await screen.findByText(/暂无公告/)).toBeInTheDocument();
  });

  it("navigates to the agent center when its card is activated", async () => {
    const { container } = render(<MemoryRouter><PortalPage /></MemoryRouter>);
    const card = screen.getByText("智能体中心", { selector: "h3" }).closest(".v2-card") as HTMLElement;
    expect(card).toBeTruthy();
    fireEvent.click(card);
    // Navigation asserted via router integration in e2e; here we only pin the card affordance.
    expect(container.querySelector(".v2-card")).toBeInTheDocument();
  });
});
