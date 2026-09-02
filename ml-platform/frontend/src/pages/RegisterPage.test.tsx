import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import RegisterPage from "./RegisterPage";

vi.mock("../api/client", () => ({ default: { post: vi.fn() } }));

describe("RegisterPage", () => {
  it("shows the current product brand in the account prompt", () => {
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>,
    );

    expect(screen.getByText("创建您的灵工账户")).toBeInTheDocument();
  });
});
