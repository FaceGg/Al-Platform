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

vi.mock("../api/securityNotifications", () => ({
  notificationsApi: notificationMocks,
}));

describe("AppLayout (v2 five-view shell)", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "en");
    localStorage.removeItem("theme");
    notificationMocks.getUnreadCount.mockReset().mockResolvedValue(2);
    notificationMocks.listInAppNotifications.mockReset().mockResolvedValue({ items: [], total: 0 });
    notificationMocks.markRead.mockReset();
    notificationMocks.archive.mockReset();
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

  it("renders the portal sidebar on the portal route", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByTestId("v2-sidebar")).toBeTruthy());
    expect(within(screen.getByTestId("v2-sidebar")).getByText("首页门户")).toBeInTheDocument();
    expect(within(screen.getByTestId("v2-sidebar")).getByText("项目管理")).toBeInTheDocument();
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

  it("keeps the five view tabs visible and switches the active view", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: /agent center/i }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/agent"));
    expect(within(screen.getByTestId("v2-sidebar")).getByText("New task (wizard)")).toBeInTheDocument();
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
