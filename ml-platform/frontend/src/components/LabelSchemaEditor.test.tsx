import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LabelSchemaEditor from "./LabelSchemaEditor";

describe("LabelSchemaEditor", () => {
  it("creates typed independent columns and saves them", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    fireEvent.change(screen.getByLabelText("机器键 1"), { target: { value: "count" } });
    fireEvent.change(screen.getByLabelText("类型 1"), { target: { value: "int" } });
    fireEvent.click(screen.getByLabelText("必填"));
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([{ machine_key: "count", display_name: "标签 1", value_type: "int", required: true }], "annotation");
  });

  it("blocks duplicate machine keys before submission", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} initialColumns={[
      { machine_key: "label", display_name: "A", value_type: "string", required: false },
      { machine_key: "label", display_name: "B", value_type: "int", required: false },
    ]} />);
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("saves numeric range and enum constraints", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    fireEvent.change(screen.getByLabelText("机器键 1"), { target: { value: "score" } });
    fireEvent.change(screen.getByLabelText("类型 1"), { target: { value: "float" } });
    fireEvent.change(screen.getByLabelText("枚举值 1"), { target: { value: "0, 0.5, 1" } });
    fireEvent.change(screen.getByLabelText("最小值 1"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("最大值 1"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([{
      machine_key: "score", display_name: "标签 1", value_type: "float", required: false,
      enum_values: [0, 0.5, 1], min_value: 0, max_value: 1,
    }], "annotation");
  });

  it("saves schema purpose and column instructions", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    fireEvent.change(screen.getByLabelText("schema 用途"), { target: { value: "training" } });
    fireEvent.change(screen.getByLabelText("列说明 1"), { target: { value: "填写焊点质量等级" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith(
      [expect.objectContaining({ instruction: "填写焊点质量等级" })],
      "training",
    );
  });
});
