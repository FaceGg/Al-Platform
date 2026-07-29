import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { LangProvider } from "../i18n";
import ProjectGovernanceTabs from "./ProjectGovernanceTabs";

const governanceMocks = vi.hoisted(() => ({
  listProjectMembers: vi.fn(),
  listProjectAuditEvents: vi.fn(),
  listProjectNotificationRecipients: vi.fn(),
  listEndpoints: vi.fn(),
  listSubscriptions: vi.fn(),
  createEndpoint: vi.fn(),
  updateEndpoint: vi.fn(),
  deleteEndpoint: vi.fn(),
  testEndpoint: vi.fn(),
  createSubscription: vi.fn(),
  updateSubscription: vi.fn(),
  deleteSubscription: vi.fn(),
  listNotificationDeliveries: vi.fn(),
  retryDelivery: vi.fn(),
}));

vi.mock("../api/securityNotifications", () => ({
  notificationsApi: governanceMocks,
}));

describe("ProjectGovernanceTabs", () => {
  beforeEach(() => {
    localStorage.setItem("lang", "en");
    governanceMocks.listProjectMembers.mockReset().mockResolvedValue({ items: [], total: 0 });
    governanceMocks.listProjectAuditEvents.mockReset().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
    governanceMocks.listProjectNotificationRecipients.mockReset().mockResolvedValue([
      { user_id: "owner-1", username: "owner-user", role: "owner" },
      { user_id: "editor-1", username: "editor-user", role: "editor" },
    ]);
    governanceMocks.listEndpoints.mockReset().mockResolvedValue({
      items: [{
        id: "endpoint-1",
        project_id: "project-1",
        kind: "webhook",
        name: "Operations receiver",
        destination_hint: "receiver.example.invalid",
        enabled: true,
        config: { signing_secret: "must-not-render" },
      }],
      total: 1,
    });
    governanceMocks.listSubscriptions.mockReset().mockResolvedValue({ items: [], total: 0 });
    governanceMocks.listNotificationDeliveries.mockReset().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
    governanceMocks.createEndpoint.mockReset().mockResolvedValue({ id: "endpoint-created" });
    governanceMocks.updateEndpoint.mockReset().mockResolvedValue({ id: "endpoint-1" });
    governanceMocks.updateSubscription.mockReset().mockResolvedValue({ id: "subscription-1" });
  });

  it("keeps notification write controls hidden from viewers and never renders endpoint configuration", async () => {
    render(
      <AntApp><LangProvider>
        <ProjectGovernanceTabs projectId="project-1" projectRole="viewer" />
      </LangProvider></AntApp>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));

    expect(await screen.findByText("receiver.example.invalid")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Add endpoint" })).not.toBeInTheDocument();
    expect(screen.queryByText("must-not-render")).not.toBeInTheDocument();
    expect(governanceMocks.listEndpoints).toHaveBeenCalledWith("project-1");
  });

  it("shows notification configuration commands for owners", async () => {
    render(
      <AntApp><LangProvider>
        <ProjectGovernanceTabs projectId="project-1" projectRole="owner" />
      </LangProvider></AntApp>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));

    expect(await screen.findByRole("button", { name: "Add endpoint" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Add subscription" })).toBeVisible();
  });

  it("requests the second audit page when more than fifty audit events exist", async () => {
    governanceMocks.listProjectAuditEvents.mockResolvedValue({
      items: [{
        id: "audit-1",
        project_id: "project-1",
        actor_id: "owner-1",
        actor_username: "owner-user",
        action: "project.update",
        resource_type: "project",
        resource_id: "project-1",
        result: "success",
        error_code: null,
        created_at: "2026-07-28T10:00:00Z",
      }],
      total: 51,
      offset: 0,
      limit: 50,
    });
    render(<AntApp><LangProvider><ProjectGovernanceTabs projectId="project-1" projectRole="owner" /></LangProvider></AntApp>);

    fireEvent.click(screen.getByRole("tab", { name: "Audit" }));
    await screen.findByText("project.update");
    fireEvent.click(screen.getByTitle("2"));

    await waitFor(() => expect(governanceMocks.listProjectAuditEvents).toHaveBeenLastCalledWith(
      "project-1",
      { offset: 50, limit: 50 },
    ));
  });

  it("requests the second delivery page when the platform delivery list exceeds fifty rows", async () => {
    governanceMocks.listNotificationDeliveries.mockResolvedValue({
      items: [{
        id: "delivery-1",
        status: "failed",
        attempts: 1,
        error_code: "NOTIFICATION_PROVIDER_REJECTED",
        destination_hint: "receiver.example.invalid",
        created_at: "2026-07-28T10:00:00Z",
        updated_at: "2026-07-28T10:00:00Z",
        next_attempt_at: null,
      }],
      total: 51,
      offset: 0,
      limit: 50,
    });
    render(<AntApp><LangProvider><ProjectGovernanceTabs projectId="project-1" projectRole="owner" isPlatformAdmin /></LangProvider></AntApp>);

    fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));
    await screen.findAllByText("receiver.example.invalid");
    fireEvent.click(screen.getByTitle("2"));

    await waitFor(() => expect(governanceMocks.listNotificationDeliveries).toHaveBeenLastCalledWith(
      { offset: 50, limit: 50 },
    ));
  });

  it("lets an editor create an in-app endpoint from the recipient selector", async () => {
    render(<AntApp><LangProvider><ProjectGovernanceTabs projectId="project-1" projectRole="editor" /></LangProvider></AntApp>);

    fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));
    fireEvent.click(await screen.findByRole("button", { name: "Add endpoint" }));
    fireEvent.mouseDown(screen.getAllByRole("combobox")[0]);
    fireEvent.click(await screen.findByText("In-app"));
    fireEvent.mouseDown(screen.getAllByRole("combobox")[1]);
    fireEvent.click(await screen.findByText("editor-user (Editor)"));
    fireEvent.change(screen.getByLabelText("Endpoint name"), { target: { value: "Editor inbox" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(governanceMocks.createEndpoint).toHaveBeenCalledWith("project-1", {
      kind: "in_app",
      name: "Editor inbox",
      config: { recipient_user_ids: ["editor-1"] },
    }));
    expect(governanceMocks.listProjectNotificationRecipients).toHaveBeenCalledWith("project-1");
  });

  it("lets an editor rename an endpoint and toggle a subscription", async () => {
    governanceMocks.listSubscriptions.mockResolvedValue({
      items: [{
        id: "subscription-1",
        project_id: "project-1",
        endpoint_id: "endpoint-1",
        event_types: ["inference.failed"],
        minimum_severity: "critical",
        recipient_roles: ["editor"],
        recipient_user_ids: ["editor-1"],
        enabled: true,
        created_by_id: "owner-1",
        created_at: null,
        updated_at: null,
      }],
      total: 1,
    });
    render(<AntApp><LangProvider><ProjectGovernanceTabs projectId="project-1" projectRole="editor" /></LangProvider></AntApp>);

    fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));
    fireEvent.click(await screen.findByRole("button", { name: "Edit endpoint" }));
    fireEvent.change(screen.getByLabelText("Endpoint name"), { target: { value: "Renamed receiver" } });
    expect(screen.queryByLabelText("Custom headers JSON")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(governanceMocks.updateEndpoint).toHaveBeenCalledWith(
      "project-1",
      "endpoint-1",
      { name: "Renamed receiver" },
    ));

    const enabledSwitches = screen.getAllByRole("switch", { name: "Enabled" });
    fireEvent.click(enabledSwitches.at(-1)!);
    await waitFor(() => expect(governanceMocks.updateSubscription).toHaveBeenCalledWith(
      "project-1",
      "subscription-1",
      { enabled: false },
    ));
  });

  it("lets an editor edit every subscription selector without typing user IDs", async () => {
    governanceMocks.listSubscriptions.mockResolvedValue({
      items: [{
        id: "subscription-1",
        project_id: "project-1",
        endpoint_id: "endpoint-1",
        event_types: ["inference.failed"],
        minimum_severity: "critical",
        recipient_roles: ["editor"],
        recipient_user_ids: ["editor-1"],
        enabled: true,
        created_by_id: "owner-1",
        created_at: null,
        updated_at: null,
      }],
      total: 1,
    });
    render(<AntApp><LangProvider><ProjectGovernanceTabs projectId="project-1" projectRole="editor" /></LangProvider></AntApp>);

    fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));
    fireEvent.click(await screen.findByRole("button", { name: "Edit subscription" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(governanceMocks.updateSubscription).toHaveBeenCalledWith(
      "project-1",
      "subscription-1",
      {
        endpoint_id: "endpoint-1",
        event_types: ["inference.failed"],
        minimum_severity: "critical",
        recipient_roles: ["editor"],
        recipient_user_ids: ["editor-1"],
        enabled: true,
      },
    ));
  });

  it("lets an editor replace an endpoint configuration without revealing the stored secret", async () => {
    render(<AntApp><LangProvider><ProjectGovernanceTabs projectId="project-1" projectRole="editor" /></LangProvider></AntApp>);

    fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));
    fireEvent.click(await screen.findByRole("button", { name: "Edit endpoint" }));
    expect(screen.queryByDisplayValue("must-not-render")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Replace configuration" }));
    fireEvent.change(screen.getByLabelText("URL"), { target: { value: "https://hooks.example.invalid/replaced" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(governanceMocks.updateEndpoint).toHaveBeenCalledWith(
      "project-1",
      "endpoint-1",
      {
        name: "Operations receiver",
        config: {
          url: "https://hooks.example.invalid/replaced",
          headers: {},
          signature_mode: "none",
        },
      },
    ));
  });

  it("keeps the in-app form when replacing an in-app endpoint configuration", async () => {
    governanceMocks.listEndpoints.mockResolvedValue({
      items: [{
        id: "endpoint-1",
        project_id: "project-1",
        kind: "in_app",
        name: "Operations inbox",
        destination_hint: "in-app recipients",
        enabled: true,
        created_by_id: "owner-1",
        created_at: null,
        updated_at: null,
      }],
      total: 1,
    });
    render(<AntApp><LangProvider><ProjectGovernanceTabs projectId="project-1" projectRole="editor" /></LangProvider></AntApp>);

    fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));
    fireEvent.click(await screen.findByRole("button", { name: "Edit endpoint" }));
    fireEvent.click(screen.getByRole("switch", { name: "Replace configuration" }));

    expect(screen.queryByLabelText("URL")).not.toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("combobox"));
    fireEvent.click(await screen.findByText("editor-user (Editor)"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(governanceMocks.updateEndpoint).toHaveBeenCalledWith(
      "project-1",
      "endpoint-1",
      {
        name: "Operations inbox",
        config: { recipient_user_ids: ["editor-1"] },
      },
    ));
  });

  it("keeps the email form when replacing an email endpoint configuration", async () => {
    governanceMocks.listEndpoints.mockResolvedValue({
      items: [{
        id: "endpoint-1",
        project_id: "project-1",
        kind: "email",
        name: "Operations email",
        destination_hint: "email recipients",
        enabled: true,
        created_by_id: "owner-1",
        created_at: null,
        updated_at: null,
      }],
      total: 1,
    });
    render(<AntApp><LangProvider><ProjectGovernanceTabs projectId="project-1" projectRole="editor" /></LangProvider></AntApp>);

    fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));
    fireEvent.click(await screen.findByRole("button", { name: "Edit endpoint" }));
    fireEvent.click(screen.getByRole("switch", { name: "Replace configuration" }));

    fireEvent.change(screen.getByLabelText("Recipients"), { target: { value: "ops@example.invalid" } });
    fireEvent.change(screen.getByLabelText("Cc recipients"), { target: { value: "backup@example.invalid" } });
    expect(screen.queryByLabelText("URL")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(governanceMocks.updateEndpoint).toHaveBeenCalledWith(
      "project-1",
      "endpoint-1",
      {
        name: "Operations email",
        config: {
          to: ["ops@example.invalid"],
          cc: ["backup@example.invalid"],
        },
      },
    ));
  });

  it("keeps the WeCom form when replacing a WeCom endpoint configuration", async () => {
    governanceMocks.listEndpoints.mockResolvedValue({
      items: [{
        id: "endpoint-1",
        project_id: "project-1",
        kind: "wecom",
        name: "Operations WeCom",
        destination_hint: "wecom.example.invalid",
        enabled: true,
        created_by_id: "owner-1",
        created_at: null,
        updated_at: null,
      }],
      total: 1,
    });
    render(<AntApp><LangProvider><ProjectGovernanceTabs projectId="project-1" projectRole="editor" /></LangProvider></AntApp>);

    fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));
    fireEvent.click(await screen.findByRole("button", { name: "Edit endpoint" }));
    fireEvent.click(screen.getByRole("switch", { name: "Replace configuration" }));

    fireEvent.change(screen.getByLabelText("URL"), { target: { value: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send" } });
    expect(screen.queryByLabelText("Custom headers JSON")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(governanceMocks.updateEndpoint).toHaveBeenCalledWith(
      "project-1",
      "endpoint-1",
      {
        name: "Operations WeCom",
        config: { url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send" },
      },
    ));
  });

  it("shows configured subscription recipients to notification managers", async () => {
    governanceMocks.listSubscriptions.mockResolvedValue({
      items: [{
        id: "subscription-1",
        project_id: "project-1",
        endpoint_id: "endpoint-1",
        event_types: ["inference.failed"],
        minimum_severity: "critical",
        recipient_roles: ["editor"],
        recipient_user_ids: ["editor-1"],
        enabled: true,
        created_by_id: "owner-1",
        created_at: null,
        updated_at: null,
      }],
      total: 1,
    });
    render(<AntApp><LangProvider><ProjectGovernanceTabs projectId="project-1" projectRole="editor" /></LangProvider></AntApp>);

    fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));

    expect(await screen.findByText("editor-user")).toBeVisible();
    expect(screen.getByText("Editor")).toBeVisible();
  });

  it("shows the specific invalid headers message for malformed webhook JSON", async () => {
    render(<AntApp><LangProvider><ProjectGovernanceTabs projectId="project-1" projectRole="editor" /></LangProvider></AntApp>);

    fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));
    fireEvent.click(await screen.findByRole("button", { name: "Add endpoint" }));
    fireEvent.change(screen.getByLabelText("Endpoint name"), { target: { value: "Broken headers" } });
    fireEvent.change(screen.getByLabelText("URL"), { target: { value: "https://hooks.example.invalid/notification" } });
    fireEvent.change(screen.getByLabelText("Custom headers JSON"), { target: { value: "{" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Headers must be a JSON object")).toBeVisible();
    expect(governanceMocks.createEndpoint).not.toHaveBeenCalled();
  });

  it("uses the configured message context for endpoint test feedback", async () => {
    governanceMocks.testEndpoint.mockResolvedValue({ status: "sent", error_code: null });
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      render(
        <AntApp>
          <LangProvider><ProjectGovernanceTabs projectId="project-1" projectRole="owner" /></LangProvider>
        </AntApp>,
      );

      fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));
      fireEvent.click(await screen.findByRole("button", { name: "Test endpoint" }));
      await waitFor(() => expect(governanceMocks.testEndpoint).toHaveBeenCalledWith("project-1", "endpoint-1"));

      expect(consoleError.mock.calls.flat().join(" ")).not.toContain(
        "Static function can not consume context",
      );
    } finally {
      consoleError.mockRestore();
    }
  });

  it("localizes audit, severity, and delivery state labels in Chinese", async () => {
    localStorage.setItem("lang", "zh");
    governanceMocks.listProjectAuditEvents.mockResolvedValue({
      items: [{
        id: "audit-1",
        project_id: "project-1",
        actor_id: "owner-1",
        actor_username: "owner-user",
        action: "project.update",
        resource_type: "project",
        resource_id: "project-1",
        result: "failed",
        error_code: null,
        created_at: "2026-07-28T10:00:00Z",
      }],
      total: 1,
      offset: 0,
      limit: 50,
    });
    governanceMocks.listSubscriptions.mockResolvedValue({
      items: [{
        id: "subscription-1",
        project_id: "project-1",
        endpoint_id: "endpoint-1",
        event_types: ["inference.failed"],
        minimum_severity: "critical",
        recipient_roles: [],
        recipient_user_ids: [],
        enabled: true,
        created_by_id: "owner-1",
        created_at: null,
        updated_at: null,
      }],
      total: 1,
    });
    governanceMocks.listNotificationDeliveries.mockResolvedValue({
      items: [{
        id: "delivery-1",
        status: "dead_letter",
        attempts: 1,
        error_code: null,
        destination_hint: "receiver.example.invalid",
        created_at: null,
        updated_at: null,
        next_attempt_at: null,
      }],
      total: 1,
      offset: 0,
      limit: 50,
    });
    render(<AntApp><LangProvider><ProjectGovernanceTabs projectId="project-1" projectRole="owner" isPlatformAdmin /></LangProvider></AntApp>);

    fireEvent.click(screen.getByRole("tab", { name: "审计" }));
    expect(await screen.findByText("失败")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "通知" }));
    expect(await screen.findByText("严重")).toBeVisible();
    expect(screen.getByText("死信")).toBeVisible();
    expect(screen.queryByText(/^critical$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^dead_letter$/)).not.toBeInTheDocument();
  });
});
