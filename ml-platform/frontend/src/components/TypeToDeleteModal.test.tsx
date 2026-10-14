import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import TypeToDeleteModal from "./TypeToDeleteModal";

describe("TypeToDeleteModal", () => {
  const baseProps = {
    open: true,
    targetName: "test112",
    description: <p>删除项目将同时删除对应的数据、API 等。</p>,
    onCancel: vi.fn(),
    onConfirm: vi.fn(),
  };

  it("disables the confirm button until the typed name matches exactly", () => {
    render(<TypeToDeleteModal {...baseProps} />);
    const okButton = screen.getByRole("button", { name: "确认删除" });
    expect(okButton).toBeDisabled();

    const input = screen.getByPlaceholderText("test112");
    fireEvent.change(input, { target: { value: "test1" } });
    expect(okButton).toBeDisabled();

    fireEvent.change(input, { target: { value: "test112 " } });
    // 首尾空白被忽略
    expect(okButton).not.toBeDisabled();
  });

  it("invokes onConfirm only after a matching name and closes via cancel", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<TypeToDeleteModal {...baseProps} onConfirm={onConfirm} onCancel={onCancel} />);

    const input = screen.getByPlaceholderText("test112");
    fireEvent.change(input, { target: { value: "wrong-name" } });
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    expect(onConfirm).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "test112" } });
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /取\s*消/ }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("clears the typed value when reopened", () => {
    const { rerender } = render(<TypeToDeleteModal {...baseProps} />);
    const input = screen.getByPlaceholderText("test112") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "test112" } });

    rerender(<TypeToDeleteModal {...baseProps} open={false} />);
    rerender(<TypeToDeleteModal {...baseProps} open={true} />);

    expect((screen.getByPlaceholderText("test112") as HTMLInputElement).value).toBe("");
    expect(screen.getByRole("button", { name: "确认删除" })).toBeDisabled();
  });
});
