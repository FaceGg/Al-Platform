import { describe, it, expect } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import AppLayout from "./AppLayout";
import { beforeEach, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { ThemeProvider } from "../stores/themeContext";

const notificationMocks = vi.hoisted(() => ({
  getUnreadCount: vi.fn(),
  listInAppNotifications: vi.fn(),
  markRead: vi.fn(),
  archive: vi.fn(),
}));
const apiMocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../api/securityNotifications", () => ({
  notificationsApi: notificationMocks,
}));
vi.mock("../api/client", () => ({ default: apiMocks }));

describe("AppLayout (v2 five-view shell)", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "en");
    localStorage.removeItem("theme");
    notificationMocks.getUnreadCount.mockReset().mockResolvedValue(2);
    notificationMocks.listInAppNotifications.mockReset().mockResolvedValue({ items: [], total: 0 });
    notificationMocks.markRead.mockReset();
    notificationMocks.archive.mockReset();
    apiMocks.get.mockReset().mockRejectedValue(new Error("offline"));
    localStorage.removeItem("role");
    localStorage.removeItem("username");
    localStorage.removeItem("token");
  });

  it("returns to the annotation task list from an active annotation run", async () => {
    function LocationProbe() {
      const location = useLocation();
      return <output data-testid="location">{location.pathname}{location.search}</output>;
    }

    render(
      <MemoryRouter initialEntries={["/data-annotation?type=spot-weld&view=workspace&projectId=project-1&runId=run-1"]}>
        <AppLayout><LocationProbe /></AppLayout>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByText("数据标注"));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/data-annotation?view=tasks"));
  });

  it("renders without crashing", async () => {
    const { container } = render(
      <MemoryRouter>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>
    );
    await waitFor(() => expect(container).toBeTruthy());
  });

  it("renders the portal route without a sidebar (design: big-card entry)", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>
    );
    // 门户无侧栏元素（v2-center 全宽布局）
    await waitFor(() => expect(screen.queryByTestId("v2-sidebar")).toBeNull());
  });

  it("renders the algo sidebar with annotation and project entries on algo routes", async () => {
    render(
      <MemoryRouter initialEntries={["/automl"]}>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByTestId("v2-sidebar")).toBeTruthy());
    expect(screen.getByText("数据标注")).toBeInTheDocument();
    expect(screen.getByText(/项目管理/)).toBeInTheDocument();
  });

  it.each([
    ["zh", "灵工"],
    ["en", "Linkraft"],
  ])("renders the %s locale brand name", async (lang, brandName) => {
    localStorage.setItem("lang", lang);

    render(
      <MemoryRouter>
        <LangProvider><AppLayout><div>test</div></AppLayout></LangProvider>
      </MemoryRouter>,
    );

    expect((await screen.findAllByText(new RegExp(brandName))).length).toBeGreaterThan(0);
  });

  it("navigates to the projects page from the algo sidebar", async () => {
    function LocationProbe() {
      const location = useLocation();
      return <output data-testid="location">{location.pathname}</output>;
    }
    render(<MemoryRouter initialEntries={["/automl"]}><AppLayout><LocationProbe /></AppLayout></MemoryRouter>);
    fireEvent.click(await screen.findByText(/项目管理/));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/projects"));
  });

  it("keeps the API marketplace entry in the algo sidebar", async () => {
    function LocationProbe() {
      const location = useLocation();
      return <output data-testid="location">{location.pathname}</output>;
    }
    render(<MemoryRouter initialEntries={["/automl"]}><AppLayout><LocationProbe /></AppLayout></MemoryRouter>);
    fireEvent.click(await screen.findByText("API市场"));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/api-marketplace"));
  });

  it("groups the algo sidebar into overview, data, modeling and serving", async () => {
    const sidebarGroups = async () => Array.from((await screen.findByTestId("v2-sidebar")).children).map((group) => ({
      label: group.querySelector(".v2-side-group")?.textContent,
      items: Array.from(group.querySelectorAll("button")).map((button) => button.textContent),
    }));
    const zhView = render(<MemoryRouter initialEntries={["/automl"]}><AppLayout><div>test</div></AppLayout></MemoryRouter>);
    expect(await sidebarGroups()).toEqual([
      { label: "概览", items: ["工作台", "项目管理"] },
      { label: "数据", items: ["数据管理", "数据标注"] },
      { label: "建模", items: ["自动建模", "模型训练", "模型库"] },
      { label: "服务", items: ["闭环自动化", "应用编排", "API市场"] },
    ]);
    zhView.unmount();

    render(<MemoryRouter initialEntries={["/automl"]}><LangProvider><AppLayout><div>test</div></AppLayout></LangProvider></MemoryRouter>);
    expect((await sidebarGroups()).map((group) => group.label)).toEqual(["Overview", "Data", "Modeling", "Serving"]);
  });

  it("marks the theme toggle and header with stable theme-aware hooks", async () => {
    render(
      <MemoryRouter>
        <LangProvider><ThemeProvider><AppLayout><div>test</div></AppLayout></ThemeProvider></LangProvider>
      </MemoryRouter>,
    );

    expect(document.querySelector(".app-header")).toBeInTheDocument();
    // Default theme is dark (v2 base) so the toggle offers switching to light mode.
    expect(await screen.findByRole("button", { name: /switch to light mode/i })).toBeInTheDocument();
  });

  it("keeps the six view tabs visible and switches the active view", async () => {
    function LocationProbe() {
      const location = useLocation();
      return <output data-testid="location">{location.pathname}</output>;
    }
    render(
      <MemoryRouter initialEntries={["/"]}>
        <LangProvider><AppLayout><LocationProbe /></AppLayout></LangProvider>
      </MemoryRouter>,
    );

    expect(screen.getByRole("button", { name: /agent center/i })).toBeInTheDocument();
    // 质量管理为第六个一级板块（2026-11-24 导航确认）
    expect(screen.getByRole("button", { name: /quality management/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /quality management/i }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/quality/scenes"));
    expect(within(screen.getByTestId("v2-sidebar")).getByText("Quality Scenes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /agent center/i }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/agent"));
    expect(within(screen.getByTestId("v2-sidebar")).getByText("New task")).toBeInTheDocument();
  });

  it("groups the quality sidebar into monitoring and configuration", async () => {
    const sidebarGroups = async () => Array.from((await screen.findByTestId("v2-sidebar")).children).map((group) => ({
      label: group.querySelector(".v2-side-group")?.textContent,
      items: Array.from(group.querySelectorAll("button")).map((button) => button.textContent),
    }));
    render(
      <MemoryRouter initialEntries={["/quality/scenes"]}>
        <LangProvider><AppLayout><div>test</div></AppLayout></LangProvider>
      </MemoryRouter>,
    );
    expect(await sidebarGroups()).toEqual([
      { label: "Monitoring", items: ["Quality Cockpit", "Realtime Monitoring", "Alert Center", "Disposition Workbench", "Production Records"] },
      { label: "Analysis", items: ["Trends & Pareto"] },
      { label: "Configuration", items: ["Quality Scenes", "Stations & Devices", "SOP Maintenance"] },
    ]);
  });

  it("shows a persistent demo-data badge when an accessible project has a demo loop (E22)", async () => {
    apiMocks.get.mockImplementation((url: string) => {
      if (url === "/demo-loop/presence") {
        return Promise.resolve({ data: { present: true, projects: [{ id: "p1", name: "演示项目" }] } });
      }
      return Promise.reject(new Error("offline"));
    });
    // 演示数据存在性只在登录态下请求（与 /auth/me 同一先例）
    localStorage.setItem("token", "test-token");
    render(
      <MemoryRouter initialEntries={["/quality/dashboard"]}>
        <LangProvider><AppLayout><div>test</div></AppLayout></LangProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("demo-presence")).toHaveTextContent("Demo data");
  });

  it("filters top tabs by the server-resolved visible views (B1 §7.1)", async () => {
    localStorage.setItem("role", "engineer");
    localStorage.setItem("token", "test-token");
    apiMocks.get.mockImplementation((url: string) => {
      if (url === "/auth/me") {
        return Promise.resolve({
          data: { id: "u1", username: "qc", role: "engineer", visible_views: ["portal", "quality"] },
        });
      }
      return Promise.reject(new Error("offline"));
    });

    render(
      <MemoryRouter initialEntries={["/quality/scenes"]}>
        <LangProvider><AppLayout><div>test</div></AppLayout></LangProvider>
      </MemoryRouter>,
    );

    // 收敛生效后：Quality Management 在位，Algorithms/Agent Center/Infrastructure 不可见
    expect(await screen.findByRole("button", { name: /quality management/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(apiMocks.get).toHaveBeenCalledWith("/auth/me");
    });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /^algorithms$/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /agent center/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /infrastructure/i })).not.toBeInTheDocument();
    });
    // 门户恒可见（登录落点不允许被收敛掉）
    expect(screen.getByRole("button", { name: /portal/i })).toBeInTheDocument();
    localStorage.removeItem("role");
    localStorage.removeItem("token");
  });

  it("selects data annotation instead of the shorter data route", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation"]}>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>,
    );

    const annotationItem = screen.getByText("数据标注").closest("button");
    const dataItem = screen.getByText("数据管理").closest("button");
    expect(annotationItem).toHaveClass("on");
    expect(dataItem).not.toHaveClass("on");
  });

  it("renders the stable notification trigger with its unread count", async () => {
    render(
      <MemoryRouter>
        <LangProvider><AppLayout><div>test</div></AppLayout></LangProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByLabelText("Notifications (2 unread)")).toBeVisible();
  });
});
