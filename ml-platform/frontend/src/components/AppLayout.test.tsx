import { describe, it, expect } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AppLayout from "./AppLayout";
import { beforeEach, vi } from "vitest";
import { screen } from "@testing-library/react";
import { LangProvider } from "../i18n";

const notificationMocks = vi.hoisted(() => ({
  getUnreadCount: vi.fn(),
  listInAppNotifications: vi.fn(),
  markRead: vi.fn(),
  archive: vi.fn(),
}));

vi.mock("../api/securityNotifications", () => ({
  notificationsApi: notificationMocks,
}));

describe("AppLayout", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "en");
    notificationMocks.getUnreadCount.mockReset().mockResolvedValue(2);
    notificationMocks.listInAppNotifications.mockReset().mockResolvedValue({ items: [], total: 0 });
    notificationMocks.markRead.mockReset();
    notificationMocks.archive.mockReset();
  });

  it("renders without crashing", async () => {
    const { container } = render(
      <MemoryRouter>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>
    );
    await waitFor(() => expect(container).toBeTruthy());
  });

  it("renders sidebar navigation", async () => {
    render(
      <MemoryRouter>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>
    );
    await waitFor(() => expect(document.querySelector(".ant-layout-sider")).toBeTruthy());
    expect(screen.getByText("数据标注")).toBeInTheDocument();
  });

  it("marks the theme toggle and header with stable theme-aware hooks", async () => {
    render(
      <MemoryRouter>
        <LangProvider><AppLayout><div>test</div></AppLayout></LangProvider>
      </MemoryRouter>,
    );

    expect(document.querySelector(".app-header")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /switch to light mode/i })).toBeInTheDocument();
  });

  it("selects data annotation instead of the shorter data route", async () => {
    render(
      <MemoryRouter initialEntries={["/data-annotation"]}>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>,
    );

    const annotationItem = screen.getByText("数据标注").closest("li");
    const dataItem = screen.getByText("数据管理").closest("li");
    expect(annotationItem).toHaveClass("ant-menu-item-selected");
    expect(dataItem).not.toHaveClass("ant-menu-item-selected");
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
