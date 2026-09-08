import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PreviewDrawer from "./PreviewDrawer";

describe("PreviewDrawer", () => {
  it("shows preview operation and closes explicitly", () => {
    const onClose = vi.fn();
    render(<PreviewDrawer open operationId="op-1" summary={{ count: 2 }} onClose={onClose} />);
    expect(screen.getByRole("dialog", { name: "任务预览" })).toBeInTheDocument();
    expect(screen.getByText(/op-1/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭预览" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
