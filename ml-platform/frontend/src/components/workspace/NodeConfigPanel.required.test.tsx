import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import NodeConfigPanel from "./NodeConfigPanel";
import { useWorkflowStore } from "../../stores/workflowStore";

describe("NodeConfigPanel required parameters", () => {
  beforeEach(() => {
    useWorkflowStore.getState().reset();
    const selectedNode = {
      id: "excel-1",
      type: "custom",
      position: { x: 0, y: 0 },
      data: { operatorId: "excel_import", label: "Excel Import", params: {} },
    } as any;
    useWorkflowStore.setState({
      nodes: [selectedNode],
      selectedNode,
      operators: [{
        id: "excel_import",
        parameters: [{
          name: "file_path",
          type: "file",
          default: "",
          label: "Data File",
          required: true,
        }],
      }],
    });
  });

  it("marks required parameter labels", () => {
    render(<NodeConfigPanel />);

    expect(screen.getByTestId("required-param-file_path")).toHaveTextContent("*");
  });

  it("marks both custom Join key selectors as required", () => {
    const selectedNode = {
      id: "join-1",
      type: "custom",
      position: { x: 0, y: 0 },
      data: { operatorId: "join", label: "Join", params: {} },
    } as any;
    useWorkflowStore.setState({
      nodes: [selectedNode],
      selectedNode,
      operators: [{
        id: "join",
        parameters: [
          { name: "left_keys", type: "str", default: "", label: "Left key", required: true },
          { name: "right_keys", type: "str", default: "", label: "Right key", required: true },
        ],
      }],
    });

    render(<NodeConfigPanel />);

    expect(screen.getByTestId("required-param-left_keys")).toHaveTextContent("*");
    expect(screen.getByTestId("required-param-right_keys")).toHaveTextContent("*");
  });

  it("marks a conditionally required field when its controller uses the default", () => {
    const selectedNode = {
      id: "csv-1",
      type: "custom",
      position: { x: 0, y: 0 },
      data: { operatorId: "csv_import", label: "CSV Import", params: {} },
    } as any;
    useWorkflowStore.setState({
      nodes: [selectedNode],
      selectedNode,
      operators: [{
        id: "csv_import",
        parameters: [
          { name: "source", type: "select", default: "local", label: "Source", options: ["local", "url"] },
          {
            name: "file_path",
            type: "file",
            default: "",
            label: "Data File",
            required: true,
            required_when: { source: "local" },
          },
        ],
      }],
    });

    render(<NodeConfigPanel />);

    expect(screen.getByTestId("required-param-file_path")).toHaveTextContent("*");
  });

  it("renders an upload control for a generic file parameter", () => {
    render(<NodeConfigPanel />);

    expect(screen.getByRole("button", { name: /浏览本地文件/ })).toBeInTheDocument();
  });

  it("shows only the local input for a local CSV import", () => {
    const selectedNode = {
      id: "csv-1",
      type: "custom",
      position: { x: 0, y: 0 },
      data: { operatorId: "csv_import", label: "CSV Import", params: { source: "local" } },
    } as any;
    useWorkflowStore.setState({
      nodes: [selectedNode],
      selectedNode,
      operators: [{
        id: "csv_import",
        parameters: [
          { name: "source", type: "select", default: "local", label: "Source", options: ["local", "url", "artifact"] },
          { name: "file_path", type: "file", default: "", label: "Data File" },
          { name: "dataset_artifact_id", type: "str", default: "", label: "Dataset Artifact ID" },
          { name: "url", type: "str", default: "", label: "File URL" },
        ],
      }],
    });

    render(<NodeConfigPanel />);

    expect(screen.getByText("Data File")).toBeInTheDocument();
    expect(screen.queryByText("Dataset Artifact ID")).not.toBeInTheDocument();
    expect(screen.queryByText("File URL")).not.toBeInTheDocument();
  });

  it("offers the artifact source for CSV imports", () => {
    const selectedNode = {
      id: "csv-1",
      type: "custom",
      position: { x: 0, y: 0 },
      data: { operatorId: "csv_import", label: "CSV Import", params: { source: "artifact" } },
    } as any;
    useWorkflowStore.setState({
      nodes: [selectedNode],
      selectedNode,
      operators: [{
        id: "csv_import",
        parameters: [
          { name: "source", type: "select", default: "local", label: "Source", options: ["local", "url", "artifact"] },
          { name: "file_path", type: "file", default: "", label: "Data File" },
          { name: "dataset_artifact_id", type: "str", default: "", label: "Dataset Artifact ID" },
          { name: "url", type: "str", default: "", label: "File URL" },
        ],
      }],
    });

    render(<NodeConfigPanel />);

    expect(screen.getByText("Dataset Artifact ID")).toBeInTheDocument();
    expect(screen.queryByText("Data File")).not.toBeInTheDocument();
    expect(screen.queryByText("File URL")).not.toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("combobox"));
    expect(screen.getAllByText("数据集制品")).toHaveLength(2);
  });
});
