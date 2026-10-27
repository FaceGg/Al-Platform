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

  it("returns to the original route captured by a 401 redirect", async () => {
    login.mockResolvedValue({ access_token: "token", user_id: "user-id", role: "admin" });

    render(
      <MemoryRouter initialEntries={["/login?redirect=%2Fagent%2Ftask%2Frun-9"]}>
        <AntApp>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/agent/task/:runId" element={<div>agent-task-page</div>} />
          </Routes>
        </AntApp>
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText("用户名"), { target: { value: "admin" } });
    fireEvent.change(screen.getByPlaceholderText("密码"), { target: { value: "password" } });
    fireEvent.click(screen.getByRole("button", { name: /登\s*录/ }));

    expect(await screen.findByText("agent-task-page")).toBeInTheDocument();
  });

  it("ignores redirect targets that are not internal paths", async () => {
    login.mockResolvedValue({ access_token: "token", user_id: "user-id", role: "admin" });

    render(
      <MemoryRouter initialEntries={["/login?redirect=https%3A%2F%2Fevil.example%2Fphish"]}>
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

    expect(await screen.findByText("authenticated-home")).toBeInTheDocument();
    expect(screen.queryByText("agent-task-page")).not.toBeInTheDocument();
  });

  it("does not report a rate limit as a bad password", async () => {
    login.mockRejectedValue({ response: { status: 429 } });

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <AntApp>
          <LoginPage />
        </AntApp>
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText("用户名"), { target: { value: "admin" } });
    fireEvent.change(screen.getByPlaceholderText("密码"), { target: { value: "admin123" } });
    fireEvent.click(screen.getByRole("button", { name: /登\s*录/ }));

    expect(await screen.findByText("登录尝试过于频繁，请稍后再试")).toBeInTheDocument();
    expect(screen.queryByText("用户名或密码错误")).not.toBeInTheDocument();
  });
});
