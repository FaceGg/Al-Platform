import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
});
