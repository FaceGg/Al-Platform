import { describe, it, expect } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AppLayout from "./AppLayout";

describe("AppLayout", () => {
  it("renders without crashing", async () => {
    const { container } = render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>
    );
    await waitFor(() => expect(container).toBeTruthy());
  });

  it("renders sidebar navigation", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>
    );
    await waitFor(() => expect(document.querySelector(".ant-layout-sider")).toBeTruthy());
  });

  it("selects the knowledge graph menu item for its route", async () => {
    const { container } = render(
      <MemoryRouter
        initialEntries={["/knowledge-graph"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(container.querySelector(".ant-menu-item-selected")?.textContent).toContain("知识图谱");
    });
  });
});
