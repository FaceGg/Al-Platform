import { fireEvent, render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UserManagementPage from "./UserManagementPage";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get, post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      common: { error: "Error", success: "Success", batch_delete: "Batch Delete" },
      nav: { users: "User Management" },
      profile: { username: "Username", role: "Role", admin: "Administrator", engineer: "Engineer", user: "User" },
    },
  }),
}));

describe("UserManagementPage", () => {
  beforeEach(() => {
    localStorage.setItem("role", "admin");
    localStorage.setItem("userId", "admin-id");
    get.mockReset();
    get.mockResolvedValue({ data: [
      { id: "admin-id", username: "admin", role: "admin", created_at: "2026-07-01T00:00:00Z" },
      { id: "member-id", username: "member", role: "user", created_at: "2026-07-02T00:00:00Z" },
    ] });
  });

  it("allows an administrator to select users for batch deletion", async () => {
    render(<AntApp><UserManagementPage /></AntApp>);

    expect(await screen.findByText("member")).toBeInTheDocument();
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(3);
    fireEvent.click(checkboxes[2]);
    expect(screen.getByRole("button", { name: /Batch Delete/ })).toBeInTheDocument();
  });
});
