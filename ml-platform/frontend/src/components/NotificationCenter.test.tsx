import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LangProvider } from "../i18n";
import NotificationCenter from "./NotificationCenter";

const notificationMocks = vi.hoisted(() => ({
  getUnreadCount: vi.fn(),
  listInAppNotifications: vi.fn(),
  markRead: vi.fn(),
  archive: vi.fn(),
}));

vi.mock("../api/securityNotifications", () => ({
  notificationsApi: notificationMocks,
}));

describe("NotificationCenter", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    localStorage.setItem("lang", "en");
    notificationMocks.getUnreadCount.mockReset()
      .mockResolvedValueOnce(2)
      .mockResolvedValueOnce(1);
    notificationMocks.listInAppNotifications.mockReset().mockResolvedValue({
      items: [{
        id: "notice-1",
        severity: "critical",
        title: "Deployment failed",
        body: "The controlled deployment receiver rejected the event.",
        created_at: "2026-07-28T10:00:00Z",
        read_at: null,
        archived_at: null,
      }],
      total: 1,
    });
    notificationMocks.markRead.mockReset().mockResolvedValue({
      id: "notice-1",
      read_at: "2026-07-28T10:01:00Z",
    });
    notificationMocks.archive.mockReset().mockResolvedValue({
      id: "notice-1",
      archived_at: "2026-07-28T10:01:00Z",
    });
  });

  it("refreshes unread notifications while visible and stops after unmount", async () => {
    vi.useFakeTimers();
    const view = render(<LangProvider><NotificationCenter /></LangProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    notificationMocks.getUnreadCount.mockReset().mockResolvedValue(3);
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(notificationMocks.getUnreadCount).toHaveBeenCalledTimes(1);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByLabelText("Notifications (3 unread)")).toBeVisible();
    view.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(notificationMocks.getUnreadCount).toHaveBeenCalledTimes(1);
  });

  it("refreshes the open list without clearing it or overlapping requests", async () => {
    render(<LangProvider><NotificationCenter /></LangProvider>);
    const trigger = await screen.findByLabelText("Notifications (2 unread)");
    fireEvent.click(trigger);
    await waitFor(() => expect(notificationMocks.listInAppNotifications).toHaveBeenCalledTimes(1));
    notificationMocks.listInAppNotifications.mockResolvedValueOnce({
      items: [{
        id: "notice-2", severity: "info", title: "Comment updated", body: "A comment was resolved.",
        created_at: "2026-09-16T10:00:00Z", read_at: null, archived_at: null,
      }],
      total: 1,
    });
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    await waitFor(() => expect(notificationMocks.listInAppNotifications).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Comment updated")).toBeInTheDocument();
  });

  it("shows unread count and marks one notification read", async () => {
    render(<LangProvider><NotificationCenter /></LangProvider>);

    const trigger = await screen.findByLabelText("Notifications (2 unread)");
    fireEvent.click(trigger);
    await waitFor(() => expect(notificationMocks.listInAppNotifications).toHaveBeenCalledTimes(1));
    const markReadButton = screen.getAllByRole("button", { name: "Mark as read" }).at(-1);
    expect(markReadButton).toBeDefined();

    fireEvent.click(markReadButton!);

    await waitFor(() => expect(notificationMocks.markRead).toHaveBeenCalledWith("notice-1"));
    await waitFor(() => expect(notificationMocks.getUnreadCount).toHaveBeenCalledTimes(2));
  });

  it("discards in-flight notification responses after unmount", async () => {
    let resolveCount!: (value: number) => void;
    let resolveList!: (value: { items: never[]; total: number }) => void;
    notificationMocks.getUnreadCount.mockReturnValueOnce(new Promise<number>((resolve) => { resolveCount = resolve; }));
    notificationMocks.listInAppNotifications.mockReturnValueOnce(
      new Promise<{ items: never[]; total: number }>((resolve) => { resolveList = resolve; }),
    );
    const view = render(<LangProvider><NotificationCenter /></LangProvider>);
    fireEvent.click(screen.getByRole("button"));
    view.unmount();
    await act(async () => {
      resolveCount(9);
      resolveList({ items: [], total: 0 });
      await Promise.resolve();
    });
    expect(screen.queryByLabelText("Notifications (9 unread)")).not.toBeInTheDocument();
  });

  it("keeps concurrent count and list responses and preserves the list on refresh failure", async () => {
    render(<LangProvider><NotificationCenter /></LangProvider>);
    fireEvent.click(await screen.findByLabelText("Notifications (2 unread)"));
    await waitFor(() => expect(screen.getByText("Deployment failed")).toBeVisible());
    let resolveCount!: (count: number) => void;
    let rejectList!: (error: Error) => void;
    notificationMocks.getUnreadCount.mockReset().mockImplementationOnce(() => new Promise(resolve => { resolveCount = resolve; }));
    notificationMocks.listInAppNotifications.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectList = reject; }));
    fireEvent.focus(window);
    fireEvent.focus(window);
    expect(notificationMocks.getUnreadCount).toHaveBeenCalledTimes(1);
    expect(notificationMocks.listInAppNotifications).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Deployment failed")).toBeVisible();
    await act(async () => {
      resolveCount(7);
      rejectList(new Error("offline"));
    });
    expect(screen.getByLabelText("Notifications (7 unread)")).toBeInTheDocument();
    expect(screen.getByText("Deployment failed")).toBeVisible();
    notificationMocks.getUnreadCount.mockRejectedValueOnce(new Error("offline"));
    await act(async () => { fireEvent.focus(window); });
    expect(screen.getByLabelText("Notifications (7 unread)")).toBeInTheDocument();
  });
});
