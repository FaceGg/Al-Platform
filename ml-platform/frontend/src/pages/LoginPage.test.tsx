import { App as AntApp } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage from "./LoginPage";

const login = vi.hoisted(() => vi.fn());
const navigate = vi.hoisted(() => vi.fn());

vi.mock("../api/auth", () => ({ login }));
vi.mock("../stores/themeContext", () => ({ useTheme: () => ({ theme: "light" }) }));
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}));

describe("LoginPage", () => {
  beforeEach(() => {
    localStorage.clear();
    login.mockReset();
    navigate.mockReset();
  });

  it("stores the username after a successful login", async () => {
    login.mockResolvedValue({ access_token: "token", user_id: "user-id", role: "admin" });

    render(
      <MemoryRouter>
        <AntApp>
          <LoginPage />
        </AntApp>
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText("用户名"), { target: { value: "admin" } });
    fireEvent.change(screen.getByPlaceholderText("密码"), { target: { value: "password" } });
    fireEvent.click(screen.getByRole("button", { name: /登\s*录/ }));

    await waitFor(() => expect(localStorage.getItem("username")).toBe("admin"));
    expect(navigate).toHaveBeenCalledWith("/");
  });
});
