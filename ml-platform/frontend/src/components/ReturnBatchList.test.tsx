import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ReturnBatchList from "./ReturnBatchList";
import type { ReturnBatch } from "../api/annotationReturns";

function batch(overrides: Partial<ReturnBatch> = {}): ReturnBatch {
  return {
    id: "batch-1",
    assignment_id: "assignment-1",
    task_revision: 2,
    state: "pending",
    created_at: null,
    operation_state: "completed",
    ...overrides,
  };
}

describe("ReturnBatchList", () => {
  it("keeps acceptance and return actions separate and requires a reason", () => {
    const onReturn = vi.fn();
    render(<ReturnBatchList items={[batch()]} loading={false} onAccept={vi.fn()} onReturn={onReturn} onDiff={vi.fn()} />);
    expect(screen.getByRole("button", { name: "验收" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "退回" }));
    expect(screen.getByRole("button", { name: "确认退回" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("退回原因"), { target: { value: "请补齐标签" } });
    fireEvent.click(screen.getByRole("button", { name: "确认退回" }));
    expect(onReturn).toHaveBeenCalledWith("batch-1", "请补齐标签", 2);
  });

  it("shows batch metadata for annotator, samples, revision, task, and time", () => {
    render(
      <ReturnBatchList
        items={[batch({
          id: "batch-9",
          task_name: "焊点质量标注",
          task_id: "task-1234567890",
          annotator_name: "张三",
          annotator_subject_id: "subject-1",
          validated_row_count: 46,
          created_at: "2026-09-21T10:00:00",
          source_dataset_name: "原始焊点数据.csv",
        })]}
        loading={false}
        onAccept={vi.fn()}
        onReturn={vi.fn()}
        onDiff={vi.fn()}
      />,
    );
    expect(screen.getByText("焊点质量标注")).toBeInTheDocument();
    expect(screen.getByText("标注员 张三")).toBeInTheDocument();
    expect(screen.getByText("46 条样本")).toBeInTheDocument();
    expect(screen.getByText("修订 2")).toBeInTheDocument();
    expect(screen.getByText("task-123")).toBeInTheDocument();
    expect(screen.getByText(/共 1 个批次 · 1 个待验收/)).toBeInTheDocument();
    expect(screen.getByText("原始焊点数据.csv")).toBeInTheDocument();
    expect(screen.queryByText(/已保存制品/)).not.toBeInTheDocument();
  });

  it("shows the saved dataset artifact once the batch has been exported", () => {
    render(
      <ReturnBatchList
        items={[batch({
          id: "batch-10",
          state: "accepted",
          task_name: "焊点质量标注",
          source_dataset_name: "原始焊点数据.csv",
          saved_dataset_name: "验收结果集.csv",
        })]}
        loading={false}
        onAccept={vi.fn()}
        onReturn={vi.fn()}
        onDiff={vi.fn()}
      />,
    );
    expect(screen.getByText("原始焊点数据.csv")).toBeInTheDocument();
    expect(screen.getByText("验收结果集.csv")).toBeInTheDocument();
    expect(screen.getByText(/已保存制品/)).toBeInTheDocument();
  });

  it("only offers review actions on pending batches", () => {
    render(
      <ReturnBatchList
        items={[batch({ id: "batch-accepted", state: "accepted", validated_row_count: 10 })]}
        loading={false}
        onAccept={vi.fn()}
        onReturn={vi.fn()}
        onDiff={vi.fn()}
      />,
    );
    expect(screen.getByText("已验收")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看差异" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "验收" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "退回" })).not.toBeInTheDocument();
  });

  it("does not call review endpoints while the return snapshot is being validated", () => {
    const onDiff = vi.fn();
    const onAccept = vi.fn();
    render(
      <ReturnBatchList
        items={[batch({ id: "batch-running", operation_state: "running" })]}
        loading={false}
        onAccept={onAccept}
        onReturn={vi.fn()}
        onDiff={onDiff}
      />,
    );
    expect(screen.getByText("校验中")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "验收" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "退回" })).not.toBeInTheDocument();
    const diff = screen.getByRole("button", { name: "等待校验" });
    expect(diff).toBeDisabled();
    fireEvent.click(diff);
    expect(onDiff).not.toHaveBeenCalled();
    expect(onAccept).not.toHaveBeenCalled();
  });
});
