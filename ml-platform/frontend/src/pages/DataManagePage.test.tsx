import { fireEvent, render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import DataManagePage from "./DataManagePage";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get } }));
vi.mock("react-router-dom", async () => ({
  ...(await vi.importActual<typeof import("react-router-dom")>("react-router-dom")),
  useNavigate: () => navigate,
}));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: {
      common: { error: "Error", cancel: "Cancel", delete: "Delete", success: "Success" },
      automl: { select_project: "Select project" },
      model: { created: "Created", actions: "Actions" },
      data: {
        title: "Data", filename: "Filename", format: "Format", size: "Size", rows: "Rows",
        preview: "Preview", download: "Download", upload_file: "Upload", export: "Export",
        batch: "Batch import", delete_file: "Delete", project: "Project",
      },
    },
  }),
}));

describe("DataManagePage", () => {
  beforeEach(() => {
    get.mockReset();
    navigate.mockReset();
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [] } });
      if (url === "/datasets") {
        return Promise.resolve({ data: { items: [{
          id: "dataset-1", project_id: "project-1", name: "weld.csv", format: "csv",
          project_name: "Weld line", file_size: 1024, row_count: 2, created_at: "2026-07-20T00:00:00Z",
        }], total: 1 } });
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
  });

  it("loads all owned datasets before a project is selected", async () => {
    render(<MemoryRouter><AntApp><DataManagePage /></AntApp></MemoryRouter>);

    expect(await screen.findByText("weld.csv")).toBeInTheDocument();
    expect(screen.getByText("Weld line")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/datasets");
  });

  it("uses compact accessible actions for each dataset row", async () => {
    render(<MemoryRouter><AntApp><DataManagePage /></AntApp></MemoryRouter>);

    expect(await screen.findByLabelText("Preview weld.csv")).toBeInTheDocument();
    expect(screen.getByLabelText("Download weld.csv")).toBeInTheDocument();
    expect(screen.getByLabelText("Delete weld.csv")).toBeInTheDocument();
    expect(document.querySelectorAll(".dataset-table-actions")).toHaveLength(1);
  });

  it("opens point-weld datasets in the dedicated annotation workspace", async () => {
    render(<MemoryRouter><AntApp><DataManagePage /></AntApp></MemoryRouter>);

    fireEvent.click(await screen.findByLabelText("质量感知 weld.csv"));

    expect(navigate).toHaveBeenCalledWith("/data-annotation?projectId=project-1&datasetId=dataset-1");
  });

  it("accepts legacy XLS report uploads alongside CSV and XLSX", async () => {
    render(<MemoryRouter><AntApp><DataManagePage /></AntApp></MemoryRouter>);

    await screen.findByText("weld.csv");
    const acceptValues = Array.from(document.querySelectorAll<HTMLInputElement>('input[type="file"]'))
      .map((input) => input.accept);
    expect(acceptValues).toContain(".csv,.xls,.xlsx,.json,.parquet");
    expect(acceptValues).toContain(".csv,.xls,.xlsx");
  });
});
