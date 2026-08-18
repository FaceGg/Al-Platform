import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AppLayout from "./AppLayout";

const apiGet = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  default: { get: apiGet },
}));

describe("AppLayout username display", () => {
  beforeEach(() => {
    localStorage.clear();
    apiGet.mockReset();
    apiGet.mockResolvedValue({ data: { username: "admin" } });
  });

  it("shows the stored username instead of the user ID", async () => {
    localStorage.setItem("userId", "f1bb5967-6295-44b7-8c0c-4905725cbfa4");
    localStorage.setItem("username", "admin");

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>,
    );

    expect(await screen.findByText("admin")).toBeInTheDocument();
    expect(screen.queryByText("f1bb5967-6295-44b7-8c0c-4905725cbfa4")).not.toBeInTheDocument();
  });

  it("loads the username for an existing session missing local storage", async () => {
    localStorage.setItem("userId", "f1bb5967-6295-44b7-8c0c-4905725cbfa4");
    localStorage.setItem("token", "token");

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>,
    );

    expect(await screen.findByText("admin")).toBeInTheDocument();
    expect(localStorage.getItem("username")).toBe("admin");
  });

  it("uses the authenticated user endpoint and never renders the UUID as identity", async () => {
    localStorage.setItem("userId", "f1bb5967-6295-44b7-8c0c-4905725cbfa4");
    localStorage.setItem("token", "token");

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>,
    );

    expect(await screen.findByText("admin")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/auth/me");
    expect(screen.queryByText("f1bb5967-6295-44b7-8c0c-4905725cbfa4")).not.toBeInTheDocument();
    expect(document.querySelector(".user-identity")).toHaveStyle({ display: "flex", flexDirection: "column", gap: "1px" });
  });
});
