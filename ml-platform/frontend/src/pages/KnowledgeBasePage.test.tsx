import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import KnowledgeBasePage from "./KnowledgeBasePage";

const { get, post, navigate } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get, post, delete: vi.fn() } }));
vi.mock("react-router-dom", () => ({ useNavigate: () => navigate }));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      common: { confirm: "Confirm", edit: "Edit", delete: "Delete", cancel: "Cancel", error: "Error", success: "Success", loading: "Loading" },
      knowledge: {
        title: "Knowledge Base", create: "New Knowledge Base", name: "Name", desc: "Description",
        delete_kb: "Delete", delete_kb_desc: "Delete this knowledge base", doc_count: "Documents",
      },
    },
  }),
}));

describe("KnowledgeBasePage", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    navigate.mockReset();
    get.mockResolvedValue({ data: [{
      id: "kb-1", name: "Welding knowledge", description: "Spot welding", document_count: 2,
    }] });
  });

  it("shows returned document counts and uses an edit action", async () => {
    render(<AntApp><KnowledgeBasePage /></AntApp>);

    expect(await screen.findByText("Documents: 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("opens a newly created knowledge base for editing", async () => {
    post.mockResolvedValue({ data: { id: "kb-new" } });
    render(<AntApp><KnowledgeBasePage /></AntApp>);

    const createLabel = await screen.findByText("New Knowledge Base");
    fireEvent.click(createLabel.closest("button")!);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New base" } });
    fireEvent.click(screen.getByRole("button", { name: "OK" }));

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith("/knowledge/bases", { name: "New base" });
      expect(navigate).toHaveBeenCalledWith("/knowledge/kb-new");
    });
  });
});
