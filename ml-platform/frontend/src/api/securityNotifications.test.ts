import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./client";
import { notificationsApi } from "./securityNotifications";

describe("securityNotifications client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("uses exact endpoint URL and returns only safe endpoint metadata", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: {
        id: "endpoint-1",
        project_id: "project-1",
        kind: "webhook",
        name: "ops",
        destination_hint: "hooks.example.invalid",
        enabled: true,
        config: { signing_secret: "must-not-reach-ui" },
      },
    });

    const endpoint = await notificationsApi.createEndpoint("project-1", {
      kind: "webhook",
      name: "ops",
      config: { url: "https://hooks.example.invalid/x" },
    });

    expect(post).toHaveBeenCalledWith(
      "/projects/project-1/notification-endpoints",
      expect.objectContaining({ kind: "webhook" }),
    );
    expect(endpoint).toMatchObject({
      id: "endpoint-1",
      destination_hint: "hooks.example.invalid",
    });
    expect(endpoint).not.toHaveProperty("config");
  });

  it("normalizes paged in-app notifications and uses recipient-private actions", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({
      data: { items: [{ id: "notice-1", title: "Deployment failed" }], total: 1 },
    });
    const patch = vi.spyOn(apiClient, "patch").mockResolvedValue({
      data: { id: "notice-1", read_at: "2026-07-28T10:00:00Z" },
    });

    const page = await notificationsApi.listInAppNotifications();
    await notificationsApi.markRead("notice-1");
    await notificationsApi.archive("notice-1");

    expect(page).toMatchObject({ items: [{ id: "notice-1", title: "Deployment failed" }], total: 1 });
    expect(get).toHaveBeenCalledWith("/notifications", { params: { include_archived: false } });
    expect(patch).toHaveBeenNthCalledWith(1, "/notifications/notice-1/read");
    expect(patch).toHaveBeenNthCalledWith(2, "/notifications/notice-1/archive");
  });

  it("passes page two parameters and reads only safe project notification recipients", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({
      data: {
        items: [{ user_id: "editor-1", username: "editor-user", role: "editor" }],
        total: 51,
        offset: 50,
        limit: 50,
      },
    });

    await notificationsApi.listProjectAuditEvents("project-1", { offset: 50, limit: 50 });
    const recipients = await notificationsApi.listProjectNotificationRecipients("project-1");
    await notificationsApi.listNotificationDeliveries({ offset: 50, limit: 50 });

    expect(get).toHaveBeenNthCalledWith(
      1,
      "/projects/project-1/audit-events",
      { params: { offset: 50, limit: 50 } },
    );
    expect(get).toHaveBeenNthCalledWith(
      2,
      "/projects/project-1/notification-recipients",
    );
    expect(get).toHaveBeenNthCalledWith(
      3,
      "/admin/notification-deliveries",
      { params: { offset: 50, limit: 50 } },
    );
    expect(recipients).toEqual([{ user_id: "editor-1", username: "editor-user", role: "editor" }]);
  });
});
