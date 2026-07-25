import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import NodeConfigPanel from "./NodeConfigPanel";
import { useWorkflowStore } from "../../stores/workflowStore";

describe("NodeConfigPanel export settings", () => {
  afterEach(() => {
    delete (window as any).showDirectoryPicker;
  });

  beforeEach(() => {
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

  it("stores a directory selected from a click-only folder picker", async () => {
    const directory = {
      name: "exports",
      getFileHandle: vi.fn(),
    };
    const showDirectoryPicker = vi.fn().mockResolvedValue(directory);
    (window as any).showDirectoryPicker = showDirectoryPicker;

    render(<NodeConfigPanel />);

    const picker = screen.getByRole("button", { name: "选择保存文件夹" });
    expect(showDirectoryPicker).not.toHaveBeenCalled();
    fireEvent.click(picker);

    await waitFor(() => expect(showDirectoryPicker).toHaveBeenCalledWith({ mode: "readwrite" }));
    expect(useWorkflowStore.getState().exportDirectories["export-1"]).toEqual({
      name: "exports",
      handle: directory,
    });
  });

  it("hides the legacy path and locks an operator with one output format", () => {
    render(<NodeConfigPanel />);

    expect(screen.getByDisplayValue("csv")).toBeDisabled();
    expect(screen.queryByText("Output File Path")).not.toBeInTheDocument();
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
