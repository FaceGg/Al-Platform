import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AssignmentDialog from "./AssignmentDialog";

describe("AssignmentDialog", () => {
  it("requires a selection and displays the overlap warning", () => {
    render(<AssignmentDialog open taskRevision={3} sampleScope={{ kind: "ids", sample_ids: ["s-1", "s-2"] }} annotators={[{ id: "a-1", username: "reviewer" }]} onClose={vi.fn()} onSubmit={vi.fn()} overlapWarning="存在重叠样本，保存时会使用修订号校验。" />);
    expect(screen.getByText("存在重叠样本，保存时会使用修订号校验。")) .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认指派" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "reviewer" }));
    expect(screen.getByRole("button", { name: "确认指派" })).toBeEnabled();
  });
});
