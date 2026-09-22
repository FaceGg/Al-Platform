import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ReturnAcceptancePanel from "./ReturnAcceptancePanel";
import * as returns from "../api/annotationReturns";

vi.mock("../api/annotationReturns", () => ({
  listReturnBatches: vi.fn(),
  diffReturnBatch: vi.fn(),
  acceptReturnBatch: vi.fn(),
  returnReturnBatch: vi.fn(),
  exportReturnBatchPreview: vi.fn(),
  exportReturnBatchDataset: vi.fn(),
}));

describe("ReturnAcceptancePanel", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(returns.listReturnBatches).mockResolvedValue({
      items: [{ id: "batch-1", assignment_id: "assignment-1", task_revision: 4, state: "pending", operation_state: "completed", validated_row_count: 2, created_at: "2026-09-20 08:00:00", task_id: "11111111-2222-3333-4444-555555555555", task_name: "任务A", annotator_subject_id: "subject-1", annotator_name: "alice" }],
      total: 1,
      next_cursor: null,
    });
    vi.mocked(returns.diffReturnBatch).mockResolvedValue({
      items: [
        { sample_id: "s-1", source_values: { x: 1 }, label_values: {} },
        { sample_id: "s-2", source_values: { x: 2 }, label_values: { fault: "hit" } },
      ],
      total: 2,
      next_cursor: null,
    });
    vi.mocked(returns.acceptReturnBatch).mockResolvedValue({ dataset_version_id: "version-1", status: "ready", version: 2 });
    vi.mocked(returns.returnReturnBatch).mockResolvedValue({ id: "batch-1", state: "returned_for_changes" });
    vi.mocked(returns.exportReturnBatchPreview).mockResolvedValue({
      return_batch_id: "batch-1",
      task_id: "task-1",
      task_name: "任务A",
      row_count: 2,
      columns: [
        { machine_key: "result", display_name: "Result", value_type: "string", mapping: { pass: 0, fail: 1 } },
      ],
    });
    vi.mocked(returns.exportReturnBatchDataset).mockResolvedValue({
      dataset_id: "dataset-1",
      name: "验收数据集",
      dataset_version_id: "version-9",
      version: 9,
      row_count: 2,
      label_mappings: { result: { pass: 0, fail: 1 } },
    });
  });

  it("renders operation-style cards with task/annotator context and no per-sample details", async () => {
    render(<ReturnAcceptancePanel projectId="project-1" />);
    // Batch cards are correlated with the task and the annotator, operations-style.
    expect(await screen.findByText("任务A")).toBeVisible();
    expect(screen.getByText(/标注员 alice/)).toBeVisible();
    expect(screen.getByText("待验收")).toBeVisible();
    expect(screen.getByText((_, element) => element?.textContent === "任务 11111111")).toBeVisible();
    // No auto-opened detail and no per-sample source data / label results.
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText("s-1")).toBeNull();
    expect(screen.queryByRole("button", { name: "验收并生成数据版本" })).toBeNull();
  });

  it("accepts a completed return batch from the drawer", async () => {
    const openSpy = vi.fn();
    vi.stubGlobal("open", openSpy);
    render(<ReturnAcceptancePanel projectId="project-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "打开验收" }));
    // Drawer shows the quality-risk summary...
    expect(await screen.findByText("1", { selector: "strong" })).toBeVisible();
    // ...but per-sample source data and label results are not rendered.
    expect(screen.queryByRole("table")).toBeNull();
    // Reviewers jump to the annotator portal for sample details.
    fireEvent.click(screen.getByRole("button", { name: "在标注员门户查看明细" }));
    expect(openSpy).toHaveBeenCalledWith(expect.stringContaining("task=11111111-2222-3333-4444-555555555555"), "_blank", "noopener");
    fireEvent.click(screen.getByRole("button", { name: "验收并生成数据版本" }));
    await waitFor(() => expect(returns.acceptReturnBatch).toHaveBeenCalledWith("batch-1", 4));
    expect(await screen.findByRole("status")).toHaveTextContent("已验收");
    vi.unstubAllGlobals();
  });

  it("requires a reason before returning a batch", async () => {
    render(<ReturnAcceptancePanel projectId="project-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "打开验收" }));
    fireEvent.click(screen.getByRole("button", { name: "退回修改" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("退回原因不能为空");
    fireEvent.change(screen.getByLabelText("退回原因"), { target: { value: "缺少必填标签" } });
    fireEvent.click(screen.getByRole("button", { name: "退回修改" }));
    await waitFor(() => expect(returns.returnReturnBatch).toHaveBeenCalledWith("batch-1", { task_revision: 4, reason: "缺少必填标签" }));
  });

  it("shows a summary-only action for batches that are not pending", async () => {
    vi.mocked(returns.listReturnBatches).mockResolvedValue({
      items: [{ id: "batch-2", assignment_id: "assignment-2", task_revision: 4, state: "accepted", operation_state: "completed", validated_row_count: 2, created_at: null, task_id: "99999999-2222-3333-4444-555555555555", task_name: "任务B", annotator_subject_id: "subject-1", annotator_name: "bob" }],
      total: 1,
      next_cursor: null,
    });
    render(<ReturnAcceptancePanel projectId="project-1" />);
    expect(await screen.findByText("已验收")).toBeVisible();
    expect(screen.getByRole("button", { name: "查看摘要" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "查看摘要" }));
    expect(await screen.findByText(/批次状态/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "验收并生成数据版本" })).toBeNull();
    expect(screen.queryByRole("button", { name: "退回修改" })).toBeNull();
  });

  it("shows the empty state when the project has no return batches", async () => {
    vi.mocked(returns.listReturnBatches).mockResolvedValue({ items: [], total: 0, next_cursor: null });
    render(<ReturnAcceptancePanel projectId="project-1" />);
    expect(await screen.findByText("暂无回传批次")).toBeVisible();
  });

  it("saves an accepted batch to data management after confirming the string-label mapping", async () => {
    vi.mocked(returns.listReturnBatches).mockResolvedValue({
      items: [{ id: "batch-2", assignment_id: "assignment-2", task_revision: 4, state: "accepted", operation_state: "completed", validated_row_count: 2, created_at: null, task_id: "99999999-2222-3333-4444-555555555555", task_name: "任务B", annotator_subject_id: "subject-1", annotator_name: "bob" }],
      total: 1,
      next_cursor: null,
    });
    render(<ReturnAcceptancePanel projectId="project-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "查看摘要" }));
    expect(await screen.findByText("保存到数据管理")).toBeVisible();
    // A dataset name is required before the label-type check runs.
    fireEvent.click(screen.getByRole("button", { name: "检测标签并保存" }));
    expect(returns.exportReturnBatchPreview).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("数据集名称"), { target: { value: "验收数据集" } });
    fireEvent.click(screen.getByRole("button", { name: "检测标签并保存" }));
    await waitFor(() => expect(returns.exportReturnBatchPreview).toHaveBeenCalledWith("batch-2"));
    // String labels show the value→int mapping and wait for confirmation.
    expect(await screen.findByRole("table")).toBeVisible();
    expect(screen.getByText("文本 · 需映射")).toBeVisible();
    expect(screen.getByText("pass")).toBeVisible();
    expect(returns.exportReturnBatchDataset).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认映射并保存到数据管理" }));
    await waitFor(() => expect(returns.exportReturnBatchDataset).toHaveBeenCalledWith("batch-2", "验收数据集", {}));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存到数据管理：验收数据集（2 条）");
  });

  it("saves directly without a mapping step when all label columns are numeric", async () => {
    vi.mocked(returns.listReturnBatches).mockResolvedValue({
      items: [{ id: "batch-3", assignment_id: "assignment-3", task_revision: 4, state: "accepted", operation_state: "completed", validated_row_count: 2, created_at: null, task_id: "99999999-2222-3333-4444-555555555555", task_name: "任务C", annotator_subject_id: "subject-1", annotator_name: "carol" }],
      total: 1,
      next_cursor: null,
    });
    vi.mocked(returns.exportReturnBatchPreview).mockResolvedValue({
      return_batch_id: "batch-3",
      task_id: "task-1",
      task_name: "任务C",
      row_count: 2,
      columns: [{ machine_key: "score", display_name: "Score", value_type: "int" }],
    });
    render(<ReturnAcceptancePanel projectId="project-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "查看摘要" }));
    fireEvent.change(await screen.findByLabelText("数据集名称"), { target: { value: "数值标签集" } });
    fireEvent.click(screen.getByRole("button", { name: "检测标签并保存" }));
    // Numeric labels (int/float) skip the mapping confirmation entirely.
    await waitFor(() => expect(returns.exportReturnBatchDataset).toHaveBeenCalledWith("batch-3", "数值标签集", {}));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存到数据管理");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("asks for an English rename before saving Chinese-named label columns", async () => {
    vi.mocked(returns.listReturnBatches).mockResolvedValue({
      items: [{ id: "batch-4", assignment_id: "assignment-4", task_revision: 4, state: "accepted", operation_state: "completed", validated_row_count: 2, created_at: null, task_id: "88888888-2222-3333-4444-555555555555", task_name: "任务D", annotator_subject_id: "subject-1", annotator_name: "dave" }],
      total: 1,
      next_cursor: null,
    });
    // Chinese column name with a numeric value type: no value mapping needed,
    // but the column still cannot be saved without an English rename.
    vi.mocked(returns.exportReturnBatchPreview).mockResolvedValue({
      return_batch_id: "batch-4",
      task_id: "task-1",
      task_name: "任务D",
      row_count: 2,
      columns: [{ machine_key: "结果", display_name: "结果", value_type: "int" }],
    });
    vi.mocked(returns.exportReturnBatchDataset).mockResolvedValue({
      dataset_id: "dataset-4",
      name: "重命名集",
      dataset_version_id: "version-10",
      version: 10,
      row_count: 2,
      label_mappings: {},
    });
    render(<ReturnAcceptancePanel projectId="project-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "查看摘要" }));
    fireEvent.change(await screen.findByLabelText("数据集名称"), { target: { value: "重命名集" } });
    fireEvent.click(screen.getByRole("button", { name: "检测标签并保存" }));
    // Chinese-named columns never save directly; the rename prompt shows up.
    expect(await screen.findByText("中文名称 · 需改为英文")).toBeVisible();
    expect(returns.exportReturnBatchDataset).not.toHaveBeenCalled();
    const renameInput = await screen.findByLabelText("英文列名 结果");
    const confirm = screen.getByRole("button", { name: "确认映射并保存到数据管理" });
    // The confirm button stays disabled until a valid English identifier is set.
    expect(confirm).toBeDisabled();
    fireEvent.change(renameInput, { target: { value: "结果" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(renameInput, { target: { value: "outcome" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(returns.exportReturnBatchDataset).toHaveBeenCalledWith("batch-4", "重命名集", { "结果": "outcome" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存到数据管理：重命名集（2 条）");
  });
});
