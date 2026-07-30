import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

  it("renders data annotation as a dedicated sidebar link", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>,
    );

    expect(await screen.findByText("数据标注")).toBeInTheDocument();
  });

  it("保持数据标注位于侧边栏首个工作项", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppLayout><div>test</div></AppLayout>
      </MemoryRouter>,
    );

    const annotationItem = (await screen.findByText("数据标注")).closest(".ant-menu-item");
    const dashboardItem = screen.getByText("工作台").closest(".ant-menu-item");

    expect(annotationItem?.parentElement?.children).toBeTruthy();
    expect(Array.from(annotationItem!.parentElement!.children).indexOf(annotationItem!))
      .toBeLessThan(Array.from(dashboardItem!.parentElement!.children).indexOf(dashboardItem!));
  });
});
