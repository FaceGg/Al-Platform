import apiClient from "./client";

export type ProjectRole = "owner" | "editor" | "operator" | "viewer";
export type NotificationEndpointKind = "in_app" | "wecom" | "email" | "webhook";
export type NotificationSeverity = "info" | "warning" | "critical";
export type NotificationDeliveryStatus = "pending" | "processing" | "sent" | "retry" | "failed" | "dead_letter";

export interface PagedResult<T> {
  items: T[];
  total: number;
  offset?: number;
  limit?: number;
}

export interface PageRequest {
  offset?: number;
  limit?: number;
}

export interface ProjectMember {
  user_id: string;
  username: string;
  role: ProjectRole;
  created_at: string | null;
}

export interface ProjectNotificationRecipient {
  user_id: string;
  username: string;
  role: ProjectRole;
}

export interface ProjectAuditEvent {
  id: string;
  project_id: string | null;
  actor_id: string | null;
  actor_username: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  result: "success" | "denied" | "failed";
  error_code: string | null;
  created_at: string;
}

export interface NotificationEndpoint {
  id: string;
  project_id: string;
  kind: NotificationEndpointKind;
  name: string;
  destination_hint: string;
  enabled: boolean;
  created_by_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface NotificationSubscription {
  id: string;
  project_id: string;
  endpoint_id: string;
  event_types: string[];
  minimum_severity: NotificationSeverity;
  recipient_roles: ProjectRole[];
  recipient_user_ids: string[];
  enabled: boolean;
  created_by_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface InAppNotification {
  id: string;
  project_id: string | null;
  event_id: string;
  event_type: string;
  severity: NotificationSeverity;
  title: string;
  body: string;
  read_at: string | null;
  archived_at: string | null;
  created_at: string | null;
}

export interface NotificationDelivery {
  id: string;
  status: NotificationDeliveryStatus;
  attempts: number;
  error_code: string | null;
  destination_hint: string;
  created_at: string | null;
  updated_at: string | null;
  next_attempt_at: string | null;
}

export interface NotificationEndpointInput {
  kind: NotificationEndpointKind;
  name: string;
  config: Record<string, unknown>;
}

export interface NotificationSubscriptionInput {
  endpoint_id: string;
  event_types: string[];
  minimum_severity: NotificationSeverity;
  recipient_roles: ProjectRole[];
  recipient_user_ids: string[];
  enabled: boolean;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function normalizePage<T>(data: unknown, normalizeItem: (value: unknown) => T): PagedResult<T> {
  const value = objectValue(data);
  const items = Array.isArray(value.items) ? value.items.map(normalizeItem) : [];
  return {
    items,
    total: typeof value.total === "number" ? value.total : items.length,
    ...(typeof value.offset === "number" ? { offset: value.offset } : {}),
    ...(typeof value.limit === "number" ? { limit: value.limit } : {}),
  };
}

function normalizeEndpoint(data: unknown): NotificationEndpoint {
  const value = objectValue(data);
  return {
    id: stringValue(value.id),
    project_id: stringValue(value.project_id),
    kind: stringValue(value.kind, "webhook") as NotificationEndpointKind,
    name: stringValue(value.name),
    destination_hint: stringValue(value.destination_hint),
    enabled: value.enabled !== false,
    created_by_id: optionalString(value.created_by_id),
    created_at: optionalString(value.created_at),
    updated_at: optionalString(value.updated_at),
  };
}

function normalizeSubscription(data: unknown): NotificationSubscription {
  const value = objectValue(data);
  return {
    id: stringValue(value.id),
    project_id: stringValue(value.project_id),
    endpoint_id: stringValue(value.endpoint_id),
    event_types: stringList(value.event_types),
    minimum_severity: stringValue(value.minimum_severity, "info") as NotificationSeverity,
    recipient_roles: stringList(value.recipient_roles) as ProjectRole[],
    recipient_user_ids: stringList(value.recipient_user_ids),
    enabled: value.enabled !== false,
    created_by_id: optionalString(value.created_by_id),
    created_at: optionalString(value.created_at),
    updated_at: optionalString(value.updated_at),
  };
}

function normalizeInAppNotification(data: unknown): InAppNotification {
  const value = objectValue(data);
  return {
    id: stringValue(value.id),
    project_id: optionalString(value.project_id),
    event_id: stringValue(value.event_id),
    event_type: stringValue(value.event_type),
    severity: stringValue(value.severity, "info") as NotificationSeverity,
    title: stringValue(value.title),
    body: stringValue(value.body),
    read_at: optionalString(value.read_at),
    archived_at: optionalString(value.archived_at),
    created_at: optionalString(value.created_at),
  };
}

function normalizeMember(data: unknown): ProjectMember {
  const value = objectValue(data);
  return {
    user_id: stringValue(value.user_id),
    username: stringValue(value.username),
    role: stringValue(value.role, "viewer") as ProjectRole,
    created_at: optionalString(value.created_at),
  };
}

function normalizeNotificationRecipient(data: unknown): ProjectNotificationRecipient {
  const value = objectValue(data);
  return {
    user_id: stringValue(value.user_id),
    username: stringValue(value.username),
    role: stringValue(value.role, "viewer") as ProjectRole,
  };
}

function pageParams(request: PageRequest): Required<PageRequest> {
  return { offset: request.offset ?? 0, limit: request.limit ?? 50 };
}

function normalizeAuditEvent(data: unknown): ProjectAuditEvent {
  const value = objectValue(data);
  return {
    id: stringValue(value.id),
    project_id: optionalString(value.project_id),
    actor_id: optionalString(value.actor_id),
    actor_username: stringValue(value.actor_username),
    action: stringValue(value.action),
    resource_type: stringValue(value.resource_type),
    resource_id: optionalString(value.resource_id),
    result: stringValue(value.result, "failed") as ProjectAuditEvent["result"],
    error_code: optionalString(value.error_code),
    created_at: stringValue(value.created_at),
  };
}

function normalizeDelivery(data: unknown): NotificationDelivery {
  const value = objectValue(data);
  return {
    id: stringValue(value.id),
    status: stringValue(value.status, "failed") as NotificationDeliveryStatus,
    attempts: typeof value.attempts === "number" ? value.attempts : 0,
    error_code: optionalString(value.error_code),
    destination_hint: stringValue(value.destination_hint),
    created_at: optionalString(value.created_at),
    updated_at: optionalString(value.updated_at),
    next_attempt_at: optionalString(value.next_attempt_at),
  };
}

export const notificationsApi = {
  async listProjectMembers(projectId: string): Promise<PagedResult<ProjectMember>> {
    const response = await apiClient.get(`/projects/${projectId}/members`);
    return normalizePage(response.data, normalizeMember);
  },

  async listProjectAuditEvents(
    projectId: string,
    request: PageRequest = {},
  ): Promise<PagedResult<ProjectAuditEvent>> {
    const response = await apiClient.get(`/projects/${projectId}/audit-events`, { params: pageParams(request) });
    return normalizePage(response.data, normalizeAuditEvent);
  },

  async listProjectNotificationRecipients(projectId: string): Promise<ProjectNotificationRecipient[]> {
    const response = await apiClient.get(`/projects/${projectId}/notification-recipients`);
    const value = objectValue(response.data);
    return Array.isArray(value.items) ? value.items.map(normalizeNotificationRecipient) : [];
  },

  async listEndpoints(projectId: string): Promise<PagedResult<NotificationEndpoint>> {
    const response = await apiClient.get(`/projects/${projectId}/notification-endpoints`);
    return normalizePage(response.data, normalizeEndpoint);
  },

  async createEndpoint(projectId: string, payload: NotificationEndpointInput): Promise<NotificationEndpoint> {
    const response = await apiClient.post(`/projects/${projectId}/notification-endpoints`, payload);
    return normalizeEndpoint(response.data);
  },

  async updateEndpoint(
    projectId: string,
    endpointId: string,
    payload: Partial<Pick<NotificationEndpointInput, "name" | "config">> & { enabled?: boolean },
  ): Promise<NotificationEndpoint> {
    const response = await apiClient.patch(`/projects/${projectId}/notification-endpoints/${endpointId}`, payload);
    return normalizeEndpoint(response.data);
  },

  async deleteEndpoint(projectId: string, endpointId: string): Promise<void> {
    await apiClient.delete(`/projects/${projectId}/notification-endpoints/${endpointId}`);
  },

  async testEndpoint(projectId: string, endpointId: string): Promise<{ status: string; error_code: string | null }> {
    const response = await apiClient.post(`/projects/${projectId}/notification-endpoints/${endpointId}/test`);
    const value = objectValue(response.data);
    return { status: stringValue(value.status, "failed"), error_code: optionalString(value.error_code) };
  },

  async listSubscriptions(projectId: string): Promise<PagedResult<NotificationSubscription>> {
    const response = await apiClient.get(`/projects/${projectId}/notification-subscriptions`);
    return normalizePage(response.data, normalizeSubscription);
  },

  async createSubscription(projectId: string, payload: NotificationSubscriptionInput): Promise<NotificationSubscription> {
    const response = await apiClient.post(`/projects/${projectId}/notification-subscriptions`, payload);
    return normalizeSubscription(response.data);
  },

  async updateSubscription(
    projectId: string,
    subscriptionId: string,
    payload: Partial<NotificationSubscriptionInput>,
  ): Promise<NotificationSubscription> {
    const response = await apiClient.patch(`/projects/${projectId}/notification-subscriptions/${subscriptionId}`, payload);
    return normalizeSubscription(response.data);
  },

  async deleteSubscription(projectId: string, subscriptionId: string): Promise<void> {
    await apiClient.delete(`/projects/${projectId}/notification-subscriptions/${subscriptionId}`);
  },

  async listInAppNotifications(includeArchived = false): Promise<PagedResult<InAppNotification>> {
    const response = await apiClient.get("/notifications", { params: { include_archived: includeArchived } });
    return normalizePage(response.data, normalizeInAppNotification);
  },

  async getUnreadCount(): Promise<number> {
    const response = await apiClient.get("/notifications/unread-count");
    const value = objectValue(response.data);
    return typeof value.count === "number" ? value.count : 0;
  },

  async markRead(notificationId: string): Promise<{ id: string; read_at: string | null }> {
    const response = await apiClient.patch(`/notifications/${notificationId}/read`);
    const value = objectValue(response.data);
    return { id: stringValue(value.id), read_at: optionalString(value.read_at) };
  },

  async archive(notificationId: string): Promise<{ id: string; archived_at: string | null }> {
    const response = await apiClient.patch(`/notifications/${notificationId}/archive`);
    const value = objectValue(response.data);
    return { id: stringValue(value.id), archived_at: optionalString(value.archived_at) };
  },

  async listNotificationDeliveries(request: PageRequest = {}): Promise<PagedResult<NotificationDelivery>> {
    const response = await apiClient.get("/admin/notification-deliveries", { params: pageParams(request) });
    return normalizePage(response.data, normalizeDelivery);
  },

  async retryDelivery(deliveryId: string): Promise<NotificationDelivery> {
    const response = await apiClient.post(`/admin/notification-deliveries/${deliveryId}/retry`);
    return normalizeDelivery(response.data);
  },
};
