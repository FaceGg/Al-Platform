import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UserManagementPage from "./UserManagementPage";

const { get, apiDelete, patch, post } = vi.hoisted(() => ({
  get: vi.fn(),
  apiDelete: vi.fn(),
  patch: vi.fn(),
  post: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get, post, put: vi.fn(), patch, delete: apiDelete } }));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      common: { error: "Error", success: "Success", batch_delete: "Batch Delete" },
      nav: { users: "User Management" },
      profile: { username: "Username", role: "Role", admin: "Administrator", engineer: "Engineer", user: "User" },
    },
  }),
}));

const annotatorItems = [
  { id: "a-1", subject_id: "subject-1", username: "pending-user", email: null, status: "pending", created_at: "2026-09-17T00:00:00Z" },
  { id: "a-2", subject_id: "subject-2", username: "active-user", email: "active@example.com", status: "active", created_at: "2026-09-16T00:00:00Z" },
  { id: "a-3", subject_id: "subject-3", username: "disabled-user", email: null, status: "disabled", created_at: "2026-09-15T00:00:00Z" },
];

describe("UserManagementPage", () => {
  beforeEach(() => {
    localStorage.setItem("role", "admin");
    localStorage.setItem("userId", "admin-id");
    get.mockReset();
    apiDelete.mockReset();
    patch.mockReset();
    post.mockReset();
    get.mockImplementation((url: string) => {
      if (url.includes("/grants")) {
        return Promise.resolve({ data: { items: [{ project_id: "project-1", status: "active" }] } });
      }
      if (url.includes("annotators")) {
        return Promise.resolve({ data: { items: annotatorItems } });
      }
      if (url === "/projects") {
        return Promise.resolve({ data: { items: [
          { id: "project-1", name: "Weld Project" },
          { id: "project-2", name: "Artifact Project" },
        ] } });
      }
      return Promise.resolve({ data: [
        { id: "admin-id", username: "admin", role: "admin", created_at: "2026-07-01T00:00:00Z" },
        { id: "member-id", username: "member", role: "user", created_at: "2026-07-02T00:00:00Z" },
      ] });
    });
    apiDelete.mockResolvedValue({ data: {} });
    patch.mockResolvedValue({ data: {} });
    post.mockResolvedValue({ data: {} });
  });

  it("allows an administrator to select users for batch deletion", async () => {
    render(<AntApp><UserManagementPage /></AntApp>);

    expect(await screen.findByText("member")).toBeInTheDocument();
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(3);
    fireEvent.click(checkboxes[2]);
    expect(screen.getByRole("button", { name: /Batch Delete/ })).toBeInTheDocument();
  });

  it("splits pending applications and approved annotators into review and management cards", async () => {
    render(<AntApp><UserManagementPage /></AntApp>);

    expect(await screen.findByText("标注员账号审核")).toBeInTheDocument();
    expect(screen.getByText("标注员管理")).toBeInTheDocument();

    const reviewCard = screen.getByText("标注员账号审核").closest(".ant-card") as HTMLElement;
    const managementCard = screen.getByText("标注员管理").closest(".ant-card") as HTMLElement;
    expect(reviewCard).not.toBeNull();
    expect(managementCard).not.toBeNull();

    expect(reviewCard).toHaveTextContent("pending-user");
    expect(reviewCard).not.toHaveTextContent("active-user");
    expect(reviewCard).not.toHaveTextContent("disabled-user");
    expect(within(reviewCard).getAllByRole("button", { name: /通\s*过/ }).length).toBeGreaterThan(0);
    expect(within(reviewCard).getAllByRole("button", { name: /删\s*除/ }).length).toBeGreaterThan(0);

    expect(managementCard).toHaveTextContent("active-user");
    expect(managementCard).toHaveTextContent("disabled-user");
    expect(managementCard).not.toHaveTextContent("pending-user");
    expect(within(managementCard).getAllByRole("button", { name: /停\s*用/ }).length).toBeGreaterThan(0);
    expect(within(managementCard).getAllByRole("button", { name: /启\s*用/ }).length).toBeGreaterThan(0);
    expect(within(managementCard).getAllByRole("button", { name: /授权项目/ })).toHaveLength(1);
    expect(within(managementCard).getAllByRole("button", { name: /重置密码/ }).length).toBeGreaterThan(0);
    expect(within(managementCard).getAllByRole("button", { name: /删\s*除/ }).length).toBeGreaterThan(0);
  });

  it("opens the grant modal with current authorizations and applies the grant/revoke diff", async () => {
    render(<AntApp><UserManagementPage /></AntApp>);

    const managementCard = await waitFor(() => {
      const card = screen.getByText("标注员管理").closest(".ant-card");
      expect(card).toHaveTextContent("active-user");
      return card as HTMLElement;
    });
    fireEvent.click(within(managementCard).getByRole("button", { name: /授权项目/ }));

    expect(await screen.findByText("项目授权：active-user")).toBeInTheDocument();
    await waitFor(() => {
      expect(document.querySelector(".ant-select-selection-item")?.textContent).toContain("Weld Project");
    });
    expect(get).toHaveBeenCalledWith("/admin/annotators/subject-2/grants");

    fireEvent.mouseDown(document.querySelector(".ant-select-selector")!);
    const dropdown = document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)") as HTMLElement;
    fireEvent.click(within(dropdown).getByTitle("Artifact Project"));
    fireEvent.click(within(dropdown).getByTitle("Weld Project"));
    fireEvent.click(screen.getByRole("button", { name: /保\s*存/ }));

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith("/internal/projects/project-2/annotators/subject-2/grant");
      expect(apiDelete).toHaveBeenCalledWith("/internal/projects/project-1/annotators/subject-2/grant");
    });
  });

  it("deletes an annotator account after confirmation", async () => {
    render(<AntApp><UserManagementPage /></AntApp>);

    const reviewCard = await waitFor(() => {
      const card = screen.getByText("标注员账号审核").closest(".ant-card");
      expect(card).toHaveTextContent("pending-user");
      return card as HTMLElement;
    });
    fireEvent.click(within(reviewCard).getAllByRole("button", { name: /删\s*除/ })[0]);
    const confirmButtons = await screen.findAllByRole("button", { name: /删\s*除/ });
    fireEvent.click(confirmButtons[confirmButtons.length - 1]);

    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith("/admin/annotators/subject-1"));
  });
});
