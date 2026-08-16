import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProjectDetailPage from "./ProjectDetailPage";

const projectDetailMocks = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock("../api/client", () => ({
  default: projectDetailMocks,
}));

vi.mock("../components/AppLayout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("./ProjectGovernanceTabs", () => ({
  default: ({ projectId, projectRole }: { projectId: string; projectRole: string | null }) => (
    <output data-testid="project-governance-role">{projectId}:{projectRole}</output>
  ),
}));

describe("ProjectDetailPage", () => {
  it("passes an editor project_role from the project API to governance controls", async () => {
    projectDetailMocks.get.mockReset()
      .mockResolvedValueOnce({ data: { id: "project-1", name: "Editor project", project_role: "editor" } })
      .mockResolvedValueOnce({ data: { items: [] } });

    render(
      <MemoryRouter initialEntries={["/projects/project-1"]}>
        <Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("project-governance-role")).toHaveTextContent("project-1:editor"));
  });
});
