import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import KnowledgeGraphPage from "./KnowledgeGraphPage";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get, post, delete: vi.fn() } }));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      common: { error: "Error", success: "Success", loading: "No data" },
      nav: { data: "Data" },
      monitor: { refresh: "Refresh" },
      knowledge: {
        graph: "Knowledge Graph", title: "Knowledge Base", add_entity: "Add entity",
        entity_name: "Entity name", entity_type: "Entity type", relation: "Relation",
        relation_type: "Relation type", entity: "Entity",
      },
    },
  }),
}));

describe("KnowledgeGraphPage", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    get.mockImplementation((url: string) => {
      if (url === "/knowledge/bases") {
        return Promise.resolve({ data: [{ id: "kb-1", name: "Weld KB" }] });
      }
      if (url === "/knowledge/bases/kb-1/graph") {
        return Promise.resolve({ data: { nodes: [], edges: [] } });
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
    post.mockResolvedValue({ data: { id: "entity-1" } });
  });

  it("creates graph entities through the canonical graph route", async () => {
    render(<AntApp><KnowledgeGraphPage /></AntApp>);

    fireEvent.mouseDown(await screen.findByRole("combobox"));
    fireEvent.click(await screen.findByText("Weld KB"));
    fireEvent.change(await screen.findByLabelText("Entity name"), { target: { value: "Heat" } });
    fireEvent.change(screen.getByLabelText("Entity type"), { target: { value: "process" } });
    fireEvent.click(screen.getByRole("button", { name: /Add entity/ }));

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(
        "/knowledge/bases/kb-1/graph/entities",
        { name: "Heat", entity_type: "process" },
      );
    });
  });
});
