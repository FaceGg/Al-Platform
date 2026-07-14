import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AppLayout from "./AppLayout";

describe("AppLayout", () => {
  it("renders without crashing", () => {
    const { container } = render(
      <MemoryRouter>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>
    );
    expect(container).toBeTruthy();
  });

  it("renders sidebar navigation", () => {
    render(
      <MemoryRouter>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>
    );
    const sider = document.querySelector(".ant-layout-sider");
    expect(sider).toBeTruthy();
  });
});
