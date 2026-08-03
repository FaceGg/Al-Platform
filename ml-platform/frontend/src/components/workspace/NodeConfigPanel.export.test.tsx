import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NodeConfigPanel from "./NodeConfigPanel";
import { useWorkflowStore } from "../../stores/workflowStore";

const datasets = vi.hoisted(() => ({
  listDatasets: vi.fn(),
  downloadDatasetArtifact: vi.fn(),
}));

vi.mock("../../api/datasets", () => datasets);

describe("NodeConfigPanel export settings", () => {
  beforeEach(() => {
    datasets.listDatasets.mockReset().mockResolvedValue([]);
    datasets.downloadDatasetArtifact.mockReset().mockResolvedValue(undefined);
    useWorkflowStore.getState().reset();
    const selectedNode = {
      id: "export-1",
      type: "custom",
      position: { x: 0, y: 0 },
      data: { operatorId: "csv_export", label: "CSV Export", params: {} },
    } as any;
    useWorkflowStore.setState({
      nodes: [selectedNode],
      selectedNode,
      operators: [{
        id: "csv_export",
        parameters: [
          { name: "file_path", type: "str", default: "", label: "Output File Path" },
          { name: "file_name", type: "str", default: "", label: "File Name" },
          { name: "format", type: "select", default: "csv", label: "Output Format", options: ["csv"] },
        ],
      }],
    });
  });

  it("does not expose a local folder picker for export operators", () => {
    render(<NodeConfigPanel />);
    expect(screen.queryByRole("button", { name: "选择保存文件夹" })).not.toBeInTheDocument();
  });

  it("hides the legacy path and locks an operator with one output format", () => {
    render(<NodeConfigPanel />);

    expect(screen.getByDisplayValue("csv")).toBeDisabled();
    expect(screen.queryByText("Output File Path")).not.toBeInTheDocument();
  });

  it("downloads the persisted dataset artifact only after the user clicks download", async () => {
    useWorkflowStore.setState({
      nodeStatuses: { "export-1": "completed" },
      nodeResults: {
        "export-1": {
          data: [{ cvei: "raw-current", cvev: "raw-voltage", cver: "raw-resistance", cvep: "raw-power" }],
          artifacts: [{ artifact_id: "artifact-1", name: "weld-export.csv", format: "csv" }],
        },
      },
    });

    render(<NodeConfigPanel />);

    expect(datasets.downloadDatasetArtifact).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "下载导出文件" }));
    await waitFor(() => expect(datasets.downloadDatasetArtifact).toHaveBeenCalledWith(
      "artifact-1",
      "weld-export.csv",
    ));
  });

  it("keeps the multi-format text exporter configurable", () => {
    const selectedNode = {
      id: "text-1",
      type: "custom",
      position: { x: 0, y: 0 },
      data: { operatorId: "write_as_text", label: "Write As Text", params: {} },
    } as any;
    useWorkflowStore.setState({
      nodes: [selectedNode],
      selectedNode,
      operators: [{
        id: "write_as_text",
        parameters: [{
          name: "format",
          type: "select",
          default: "text",
          label: "Output Format",
          options: ["json", "csv", "text"],
        }],
      }],
    });

    render(<NodeConfigPanel />);

    expect(screen.getByRole("combobox")).not.toBeDisabled();
  });
});
