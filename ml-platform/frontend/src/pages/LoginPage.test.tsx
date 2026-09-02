import { App as AntApp } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage from "./LoginPage";

const login = vi.hoisted(() => vi.fn());

vi.mock("../api/auth", () => ({ login }));
vi.mock("../stores/themeContext", () => ({ useTheme: () => ({ theme: "light" }) }));

describe("LoginPage", () => {
  beforeEach(() => {
    localStorage.clear();
    login.mockReset();
  });

  it("shows the current product brand", () => {
    render(
      <MemoryRouter>
        <AntApp>
          <LoginPage />
        </AntApp>
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "灵工" })).toBeInTheDocument();
  });

  it("stores the username after a successful login", async () => {
    login.mockResolvedValue({ access_token: "token", user_id: "user-id", role: "admin" });

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <AntApp>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<div>authenticated-home</div>} />
          </Routes>
        </AntApp>
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText("用户名"), { target: { value: "admin" } });
    fireEvent.change(screen.getByPlaceholderText("密码"), { target: { value: "password" } });
    fireEvent.click(screen.getByRole("button", { name: /登\s*录/ }));

    await waitFor(() => expect(localStorage.getItem("username")).toBe("admin"));
    expect(await screen.findByText("authenticated-home")).toBeInTheDocument();
  });
});
