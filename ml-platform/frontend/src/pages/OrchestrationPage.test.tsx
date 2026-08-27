import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OrchestrationPage from "./OrchestrationPage";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  apiGet: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({
  default: api,
  apiGet: api.apiGet,
  apiPost: api.post,
  apiDelete: api.delete,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    lang: "en",
    t: {
      common: { delete: "Delete", success: "Success" },
      knowledge: { name: "Name", desc: "Description" },
      training: { status: "Status", started: "Created" },
      model: { actions: "Actions" },
      orchestration: {
        title: "Orchestration", tasks: "Tasks", agents: "Agents", new_task: "New task",
        new_agent: "New agent", assigned_agent: "Agent", requires_review: "Review",
        priority: "Priority", plan: "Plan", planner: "Planner", executor: "Executor", reviewer: "Reviewer",
      },
    },
  }),
}));

describe("OrchestrationPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.apiGet.mockImplementation((url: string) => Promise.resolve(url === "/orchestration/agents" ? { items: [{ id: "agent-1", name: "Planner A", agent_type: "planner", model_name: "gpt", is_active: true }] } : []));
    api.get.mockImplementation((url: string, config?: { params?: { project_id?: string } }) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [
        { id: "project-1", name: "Line A" },
        { id: "project-2", name: "Line B" },
      ] } });
      if (url === "/orchestration/tasks") return Promise.resolve({ data: [{
        id: config?.params?.project_id ? "task-filtered" : "task-all",
        name: "Inspect welds",
        project_id: config?.params?.project_id || "project-1",
        project_name: config?.params?.project_id ? "Line B" : "Line A",
        created_by_name: "alice",
        status: "pending",
        priority: 1,
        requires_review: false,
        created_at: "2026-08-26T00:00:00Z",
      }] });
      return Promise.resolve({ data: [] });
    });
  });

  it("shows all accessible tasks by default with project and creator columns", async () => {
    render(<OrchestrationPage />);

    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/orchestration/tasks", { params: undefined }));
    expect(screen.getByRole("columnheader", { name: "Project" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Creator" })).toBeInTheDocument();
    expect(await screen.findByText("Line A")).toBeInTheDocument();
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByText("All projects")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Actions" })).toHaveStyle({ textAlign: "right" });
  });

  it("filters tasks after a project is selected", async () => {
    render(<OrchestrationPage />);

    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "Project" }));
    fireEvent.click(await screen.findByText("Line B"));

    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/orchestration/tasks", {
      params: { project_id: "project-2" },
    }));
  });

  it("confirms task and agent row deletion", async () => {
    render(<OrchestrationPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Delete Inspect welds" }));
    expect(api.delete).not.toHaveBeenCalled();
    fireEvent.click(within(await screen.findByRole("tooltip")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/orchestration/tasks/task-all"));

    fireEvent.click(screen.getByRole("tab", { name: "Agents" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete Planner A" }));
    expect(api.delete).not.toHaveBeenCalledWith("/orchestration/agents/agent-1");
    fireEvent.click(within(await screen.findByRole("tooltip")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/orchestration/agents/agent-1"));
  });

  it("confirms task and agent batch deletion with the selected count", async () => {
    render(<OrchestrationPage />);

    fireEvent.click((await screen.findAllByRole("checkbox"))[0]);
    fireEvent.click(await screen.findByRole("button", { name: /批量删除 \(1\)/ }));
    expect(api.post).not.toHaveBeenCalledWith("/orchestration/batch-delete", { ids: ["task-all"] });
    expect(await screen.findByText("Delete the selected 1 items?This action cannot be undone.")).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("tooltip")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/orchestration/batch-delete", { ids: ["task-all"] }));

    fireEvent.click(screen.getByRole("tab", { name: "Agents" }));
    fireEvent.click((await screen.findAllByRole("checkbox"))[0]);
    fireEvent.click(await screen.findByRole("button", { name: /Delete selected agents \(1\)/ }));
    fireEvent.click(within(await screen.findByRole("tooltip")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/orchestration/agents/batch-delete", { ids: ["agent-1"] }));
  });
});
