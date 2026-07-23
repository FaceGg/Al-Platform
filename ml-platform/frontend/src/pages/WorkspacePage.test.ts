import { describe, expect, it } from "vitest";
import { hydrateWorkflowEdges, resolvePort } from "./WorkspacePage";
import { isVisualizationResultNode } from "../components/workspace/WorkflowCanvas";

describe("workspace port persistence", () => {
  const ports = [{ name: "data" }, { name: "predictions" }];

  it("resolves indexed ReactFlow handles to operator port names", () => {
    expect(resolvePort("out-1", ports)).toBe("predictions");
    expect(resolvePort("in-0", ports)).toBe("data");
  });

  it("preserves named and unknown handles", () => {
    expect(resolvePort("model", ports)).toBe("model");
    expect(resolvePort("out-9", ports)).toBe("out-9");
  });

  it("maps dynamic handle slots back to their logical port", () => {
    expect(resolvePort("data__slot_2", ports)).toBe("data");
  });

  it("normalizes legacy slot handles during hydration", () => {
    expect(hydrateWorkflowEdges([
      {
        id: "e",
        source: "a",
        target: "b",
        source_port: "data__slot_3",
        target_port: "in__slot_2",
      },
    ])[0]).toMatchObject({
      source: "a",
      target: "b",
      sourceHandle: "data",
      targetHandle: "in",
    });
  });

  it("keeps only the latest edge for each normalized source or target endpoint", () => {
    expect(hydrateWorkflowEdges([
      {
        id: "source-first",
        source: "source-a",
        target: "target-a",
        source_port: "data__slot_0",
        target_port: "input__slot_0",
      },
      {
        id: "source-latest",
        source: "source-a",
        target: "target-b",
        source_port: "data__slot_1",
        target_port: "input__slot_0",
      },
      {
        id: "target-first",
        source: "source-c",
        target: "target-c",
        source_port: "data__slot_0",
        target_port: "input__slot_0",
      },
      {
        id: "target-latest",
        source: "source-d",
        target: "target-c",
        source_port: "data__slot_0",
        target_port: "input__slot_1",
      },
    ])).toEqual([
      {
        id: "source-latest",
        source: "source-a",
        target: "target-b",
        sourceHandle: "data",
        targetHandle: "input",
      },
      {
        id: "target-latest",
        source: "source-d",
        target: "target-c",
        sourceHandle: "data",
        targetHandle: "input",
      },
    ]);
  });
});

describe("visualization result click gating", () => {
  const node = {
    id: "viz-1",
    data: { operatorId: "line_chart", category: "visualization" },
  };

  it("allows canvas result opening only for completed visualization nodes", () => {
    expect(isVisualizationResultNode(node, "completed")).toBe(true);
    expect(isVisualizationResultNode(node, "running")).toBe(false);
    expect(isVisualizationResultNode({ ...node, data: { ...node.data, category: "processing" } }, "completed")).toBe(false);
  });

  it("falls back to operator metadata when a node has no category", () => {
    expect(isVisualizationResultNode({ id: "viz-2", data: { operatorId: "line_chart" } }, "completed", [
      { id: "line_chart", category: "visualization" },
    ])).toBe(true);
  });
});
