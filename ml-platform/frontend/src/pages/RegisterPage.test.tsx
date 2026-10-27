import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import RegisterPage from "./RegisterPage";

const post = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  default: { post },
  formatApiError: (error: any, fallback: string) =>
    error?.response?.data?.detail?.message || fallback,
}));

// 合规口令运行时生成（大写+小写+数字+符号），避免测试源码出现可用凭据字面量
function strongSamplePassword(): string {
  return `Str0ng-${Math.random().toString(36).slice(2, 8)}`;
}

function fillForm(username: string, password: string) {
  fireEvent.change(screen.getByPlaceholderText("用户名"), { target: { value: username } });
  fireEvent.change(screen.getByPlaceholderText("密码"), { target: { value: password } });
}

describe("RegisterPage", () => {
  it("shows the current product brand in the account prompt", () => {
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>,
    );

    expect(screen.getByText("创建您的灵工账户")).toBeInTheDocument();
  });

  it("blocks submission when the password mixes fewer than three character classes", async () => {
    post.mockReset();
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>,
    );

    fillForm("policy-user", "weakpass99");
    fireEvent.click(screen.getByRole("button", { name: "注 册" }));

    expect(await screen.findByText("密码必须包含数字、大写字母、小写字母、符号中的至少 3 种")).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it("requires at least eight characters before the class rule applies", async () => {
    post.mockReset();
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>,
    );

    fillForm("policy-user", "Ab1");
    fireEvent.click(screen.getByRole("button", { name: "注 册" }));

    expect(await screen.findByText("密码至少 8 位")).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it("submits when the password contains three or more character classes", async () => {
    post.mockReset();
    post.mockResolvedValue({ status: 200 });
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>,
    );

    const password = strongSamplePassword();
    fillForm("policy-user", password);
    fireEvent.click(screen.getByRole("button", { name: "注 册" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/auth/register", {
        username: "policy-user",
        password,
        role: "engineer",
      }),
    );
  });
});
