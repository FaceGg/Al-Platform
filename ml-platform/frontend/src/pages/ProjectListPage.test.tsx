import { render, screen } from "@testing-library/react";
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
});
