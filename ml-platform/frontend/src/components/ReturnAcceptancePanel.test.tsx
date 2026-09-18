import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ReturnAcceptancePanel from "./ReturnAcceptancePanel";
import * as returns from "../api/annotationReturns";

vi.mock("../api/annotationReturns", () => ({
  listReturnBatches: vi.fn(),
  diffReturnBatch: vi.fn(),
  acceptReturnBatch: vi.fn(),
  returnReturnBatch: vi.fn(),
}));

describe("ReturnAcceptancePanel", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(returns.listReturnBatches).mockResolvedValue({
      items: [{ id: "batch-1", assignment_id: "assignment-1", task_revision: 4, state: "pending", operation_state: "completed", validated_row_count: 2, created_at: null }],
      total: 1,
      next_cursor: null,
    });
    vi.mocked(returns.diffReturnBatch).mockResolvedValue({
      items: [{ sample_id: "s-1", source_values: { x: 1 }, label_values: {} }],
      total: 1,
      next_cursor: null,
    });
    vi.mocked(returns.acceptReturnBatch).mockResolvedValue({ dataset_version_id: "version-1", status: "ready", version: 2 });
    vi.mocked(returns.returnReturnBatch).mockResolvedValue({ id: "batch-1", state: "returned_for_changes" });
  });

  it("shows frozen diff and accepts a completed return batch", async () => {
    render(<ReturnAcceptancePanel projectId="project-1" />);
    expect(await screen.findByText("batch-1")).toBeVisible();
    expect(await screen.findByText("标签为空")).toBeVisible();
    expect(screen.getByText(/质量风险：/)).toBeVisible();
    expect(screen.getByText("1", { selector: "strong" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "验收并生成数据版本" }));
    await waitFor(() => expect(returns.acceptReturnBatch).toHaveBeenCalledWith("batch-1", 4));
    expect(await screen.findByRole("status")).toHaveTextContent("已验收");
  });

  it("requires a reason before returning a batch", async () => {
    render(<ReturnAcceptancePanel projectId="project-1" />);
    await screen.findByText("batch-1");
    fireEvent.click(screen.getByRole("button", { name: "退回修改" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("退回原因不能为空");
    fireEvent.change(screen.getByLabelText("退回原因"), { target: { value: "缺少必填标签" } });
    fireEvent.click(screen.getByRole("button", { name: "退回修改" }));
    await waitFor(() => expect(returns.returnReturnBatch).toHaveBeenCalledWith("batch-1", { task_revision: 4, reason: "缺少必填标签" }));
  });
});
