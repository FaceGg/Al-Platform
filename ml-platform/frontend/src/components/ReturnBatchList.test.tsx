import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ReturnBatchList from "./ReturnBatchList";

describe("ReturnBatchList", () => {
  it("keeps acceptance and return actions separate and requires a reason", () => {
    const onReturn = vi.fn();
    render(<ReturnBatchList items={[{ id: "batch-1", assignment_id: "assignment-1", task_revision: 2, state: "pending", created_at: null }]} onAccept={vi.fn()} onReturn={onReturn} onDiff={vi.fn()} />);
    expect(screen.getByRole("button", { name: "验收" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "退回" }));
    expect(screen.getByRole("button", { name: "确认退回" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("退回原因"), { target: { value: "请补齐标签" } });
    fireEvent.click(screen.getByRole("button", { name: "确认退回" }));
    expect(onReturn).toHaveBeenCalledWith("batch-1", "请补齐标签", 2);
  });
});
