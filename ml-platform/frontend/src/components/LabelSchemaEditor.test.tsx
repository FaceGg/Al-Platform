import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LabelSchemaEditor from "./LabelSchemaEditor";

describe("LabelSchemaEditor", () => {
  it("creates columns with read-only auto-incremented machine keys and saves enums", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    expect(screen.getByText("label-1")).toBeInTheDocument();
    // 机器键为只读展示，不再是可编辑输入框
    expect(screen.queryByRole("textbox", { name: "机器键 1" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("类型 1"), { target: { value: "int" } });
    // 默认约束方式为枚举值；类型为 int 时枚举值输入为数字
    expect(screen.getByLabelText("约束方式 1")).toHaveValue("enum");
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "添加枚举值 1" }));
    fireEvent.change(screen.getByLabelText("枚举值 1 值 2"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([{ machine_key: "label-1", display_name: "标签-1", value_type: "int", required: true, enum_values: [0, 1] }], "annotation");
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

  it("saves numeric range and enum constraints after choosing enum_and_range", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    fireEvent.change(screen.getByLabelText("类型 1"), { target: { value: "float" } });
    fireEvent.change(screen.getByLabelText("约束方式 1"), { target: { value: "enum_range" } });
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "0.5" } });
    fireEvent.change(screen.getByLabelText("最小值 1"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("最大值 1"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([{
      machine_key: "label-1", display_name: "标签-1", value_type: "float", required: true,
      enum_values: [0.5], min_value: 0, max_value: 1,
    }], "annotation");
  });

  it("rejects empty or type-mismatched enum values and empty ranges", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    fireEvent.change(screen.getByLabelText("类型 1"), { target: { value: "int" } });
    // 枚举值为空 → 拒绝
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    // 枚举值与整数类型不匹配 → 拒绝
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    // 范围缺最大值 → 拒绝
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("约束方式 1"), { target: { value: "range" } });
    fireEvent.change(screen.getByLabelText("最小值 1"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
    // 补全后通过
    fireEvent.change(screen.getByLabelText("最大值 1"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([expect.objectContaining({ min_value: 0, max_value: 10 })], "annotation");
  });

  it("only offers enum constraints for string columns", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    expect(screen.getByLabelText("约束方式 1")).toHaveValue("enum");
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "ok" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([expect.objectContaining({ value_type: "string", enum_values: ["ok"], required: true })], "annotation");
    expect(screen.queryByLabelText("最小值 1")).not.toBeInTheDocument();
  });

  it("removes an enum value with the per-row delete button", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "a" } });
    fireEvent.click(screen.getByRole("button", { name: "添加枚举值 1" }));
    fireEvent.change(screen.getByLabelText("枚举值 1 值 2"), { target: { value: "b" } });
    fireEvent.click(screen.getByRole("button", { name: "删除枚举值 1 值 2" }));
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([expect.objectContaining({ enum_values: ["a"] })], "annotation");
  });

  it("saves schema purpose and column instructions", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    fireEvent.change(screen.getByLabelText("schema 用途"), { target: { value: "training" } });
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("列说明 1"), { target: { value: "填写焊点质量等级" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith(
      [expect.objectContaining({ instruction: "填写焊点质量等级" })],
      "training",
    );
  });

  it("keeps default columns undeletable while added columns can be removed", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} initialColumns={[
      { machine_key: "label-1", display_name: "标签-1", value_type: "string", required: true, isDefault: true },
    ]} />);
    // 默认列可修改但不可删除
    expect(screen.queryByRole("button", { name: "删除列 1" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("标签名称 1"), { target: { value: "改名" } });

    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    expect(screen.getByText("label-2")).toBeInTheDocument();
    // 新增的列可以删除
    fireEvent.click(screen.getByRole("button", { name: "删除列 2" }));
    expect(screen.queryByText("label-2")).not.toBeInTheDocument();
    // 修改默认列不受删除操作影响
    expect(screen.getByLabelText("标签名称 1")).toHaveValue("改名");
  });

  it("hides the purpose select and keeps required when showPurpose is false", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor showPurpose={false} onSave={onSave} initialColumns={[
      { machine_key: "label-1", display_name: "标签-1", value_type: "string", required: false },
    ]} />);
    expect(screen.queryByLabelText("schema 用途")).not.toBeInTheDocument();
    expect(screen.queryByText("必填")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "ok" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([{ machine_key: "label-1", display_name: "标签-1", value_type: "string", required: true, enum_values: ["ok"] }], "annotation");
  });
});
