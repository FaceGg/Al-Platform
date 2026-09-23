import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AssignmentDialog from "./AssignmentDialog";

describe("AssignmentDialog", () => {
  it("requires a dropdown selection, submits selected ids, and displays the overlap warning", () => {
    const onSubmit = vi.fn();
    render(<AssignmentDialog open taskRevision={3} sampleScope={{ kind: "ids", sample_ids: ["s-1", "s-2"] }} annotators={[{ id: "a-1", username: "reviewer" }]} onClose={vi.fn()} onSubmit={onSubmit} overlapWarning="存在重叠样本，保存时会使用修订号校验。" />);
    expect(screen.getByText("存在重叠样本，保存时会使用修订号校验。")) .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认指派" })).toBeDisabled();
    fireEvent.mouseDown(document.querySelector(".ant-select-selector")!);
    fireEvent.click(screen.getByTitle("reviewer"));
    expect(screen.getByRole("button", { name: "确认指派" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "确认指派" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ annotator_ids: ["a-1"] }));
  });

  it("renders as a right drawer and closes when the mask is clicked", () => {
    const onClose = vi.fn();
    render(<AssignmentDialog open taskRevision={1} sampleScope={{ kind: "frozen_task_scope" }} annotators={[]} onClose={onClose} onSubmit={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: "指派任务" })).toBeInTheDocument();
    const mask = document.querySelector(".ant-drawer-mask");
    expect(mask).not.toBeNull();
    fireEvent.click(mask!);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("prompts for project authorization when no granted annotators are loaded", () => {
    const hint = "该项目暂无已授权标注员，请先在用户管理 → 标注员管理中完成项目授权";
    const { rerender } = render(<AssignmentDialog open taskRevision={1} sampleScope={{ kind: "frozen_task_scope" }} annotators={[]} loading onClose={vi.fn()} onSubmit={vi.fn()} />);
    expect(screen.queryByText(hint)).not.toBeInTheDocument();
    rerender(<AssignmentDialog open taskRevision={1} sampleScope={{ kind: "frozen_task_scope" }} annotators={[]} onClose={vi.fn()} onSubmit={vi.fn()} />);
    expect(screen.getByRole("note")).toHaveTextContent(hint);
  });

  it("shows annotator details (email and review status) in the dropdown options", () => {
    render(<AssignmentDialog open taskRevision={1} sampleScope={{ kind: "frozen_task_scope" }} annotators={[{ id: "a-1", username: "reviewer", email: "reviewer@example.com" }]} onClose={vi.fn()} onSubmit={vi.fn()} />);
    fireEvent.mouseDown(document.querySelector(".ant-select-selector")!);
    expect(screen.getByTitle("reviewer")).toBeInTheDocument();
    expect(screen.getByText(/reviewer@example\.com · 已审核通过 · 已授权本项目/)).toBeInTheDocument();
  });

  it("shows the review status fallback when an annotator has no email", () => {
    render(<AssignmentDialog open taskRevision={1} sampleScope={{ kind: "frozen_task_scope" }} annotators={[{ id: "a-1", username: "reviewer" }]} onClose={vi.fn()} onSubmit={vi.fn()} />);
    fireEvent.mouseDown(document.querySelector(".ant-select-selector")!);
    expect(screen.getByText("已审核通过 · 已授权本项目")).toBeInTheDocument();
  });

  it("lists already-assigned annotators and excludes them from the dropdown", () => {
    render(
      <AssignmentDialog
        open
        taskRevision={2}
        sampleScope={{ kind: "frozen_task_scope" }}
        annotators={[{ id: "a-1", username: "alice" }, { id: "a-2", username: "bob" }]}
        assignedIds={["a-1"]}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByText("已指派标注员（1）")).toBeInTheDocument();
    expect(screen.getByText("alice")).toBeInTheDocument();
    fireEvent.mouseDown(document.querySelector(".ant-select-selector")!);
    expect(screen.getByTitle("bob")).toBeInTheDocument();
    expect(screen.queryByTitle("alice")).not.toBeInTheDocument();
  });

  it("shows an exhausted hint when every annotator is already assigned", () => {
    render(
      <AssignmentDialog
        open
        taskRevision={2}
        sampleScope={{ kind: "frozen_task_scope" }}
        annotators={[{ id: "a-1", username: "alice" }]}
        assignedIds={["a-1"]}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    fireEvent.mouseDown(document.querySelector(".ant-select-selector")!);
    expect(screen.getByText("该项目标注员均已指派")).toBeInTheDocument();
  });
});
