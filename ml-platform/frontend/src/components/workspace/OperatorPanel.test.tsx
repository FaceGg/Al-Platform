import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import OperatorPanel from "./OperatorPanel";
import { useWorkflowStore } from "../../stores/workflowStore";

describe("OperatorPanel", () => {
  beforeEach(() => {
    useWorkflowStore.getState().reset();
    useWorkflowStore.getState().setOperators([
      { id: "csv_import", name: "CSV / Excel Import", category: "io", description: "Import tabular data" },
      { id: "optimize_grid", name: "Grid Optimization", category: "optimization", description: "Search parameters" },
    ]);
  });

  it("localizes IO and optimization categories while keeping groups collapsed by default", () => {
    render(<OperatorPanel />);

    expect(screen.getByText("数据输入输出")).toBeInTheDocument();
    expect(screen.getByText("参数优化")).toBeInTheDocument();
    expect(screen.queryByText("CSV/Excel导入")).not.toBeInTheDocument();
  });
});
