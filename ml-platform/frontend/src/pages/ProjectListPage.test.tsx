import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import ProjectListPage from "./ProjectListPage";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("../api/client", () => ({ default: api }));
vi.mock("../components/AppLayout", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("../i18n", () => ({ useI18n: () => ({ t: {} }) }));

describe("ProjectListPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockResolvedValue({
      data: {
        items: [{
          id: "project-1",
          name: "点焊质量感知",
          description: "",
          creator_username: "admin",
          created_at: "2026-08-11T10:00:00",
        }],
      },
    });
  });

  it("shows the creator for every listed project", async () => {
    render(
      <MemoryRouter>
        <AntApp>
          <ProjectListPage />
        </AntApp>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("columnheader", { name: "创建者" })).toBeInTheDocument();
    expect(screen.getByText("admin")).toBeInTheDocument();
  });

  it("uses icon-only row actions with named hover tooltips", async () => {
    render(
      <MemoryRouter>
        <AntApp>
          <ProjectListPage />
        </AntApp>
      </MemoryRouter>,
    );

    const deleteButton = await screen.findByRole("button", { name: "删除项目 点焊质量感知" });
    expect(deleteButton).toHaveClass("table-row-action--danger");
    expect(deleteButton).not.toHaveTextContent("删除");
    fireEvent.mouseEnter(deleteButton.parentElement!);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("删除项目 点焊质量感知");
    expect(screen.getByRole("columnheader", { name: "操作" })).toHaveStyle({ textAlign: "right" });
  });

  it("requires the shared confirmation for row and batch deletion", async () => {
    api.delete.mockResolvedValue({});
    api.post.mockResolvedValue({});
    render(<MemoryRouter><AntApp><ProjectListPage /></AntApp></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: "删除项目 点焊质量感知" }));
    expect(api.delete).not.toHaveBeenCalled();
    fireEvent.click(within(await screen.findByRole("tooltip")).getByRole("button", { name: /删\s*除/ }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/projects/project-1"));

    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.click(await screen.findByRole("button", { name: /批量删除 \(1\)/ }));
    expect(api.post).not.toHaveBeenCalledWith("/projects/batch-delete", { ids: ["project-1"] });
    fireEvent.click(within(await screen.findByRole("tooltip")).getByRole("button", { name: /删\s*除/ }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/projects/batch-delete", { ids: ["project-1"] }));
  });
});
