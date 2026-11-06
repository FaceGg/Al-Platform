import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LabelSchemaEditor, { defaultLabelColumns } from "./LabelSchemaEditor";

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

  it("derives the machine key from the user-entered label name", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    fireEvent.change(screen.getByLabelText("标签名称 1"), { target: { value: "质量等级" } });
    // 机器键实时跟随标签名称（空白转下划线）
    expect(screen.getByText("质量等级")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("标签名称 1"), { target: { value: "quality level" } });
    expect(screen.getByText("quality_level")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "ok" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith(
      [expect.objectContaining({ machine_key: "quality_level", display_name: "quality level" })],
      "annotation",
    );
  });

  it("keeps the contract machine key when the prefilled name is untouched", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} initialColumns={[
      { machine_key: "quality", display_name: "质量", value_type: "string", required: true, isDefault: true },
    ]} />);
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "ok" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith(
      [expect.objectContaining({ machine_key: "quality", display_name: "质量" })],
      "annotation",
    );
  });

  it("rejects label names that cannot become machine keys", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    fireEvent.change(screen.getByLabelText("标签名称 1"), { target: { value: "质量(A)" } });
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "ok" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
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

  it("offers enum only for strings and exclusive enum or range for numeric types", () => {
    render(<LabelSchemaEditor onSave={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    const modes = () => within(screen.getByLabelText("约束方式 1")).getAllByRole("option").map((option) => option.textContent);
    expect(modes()).toEqual(["枚举值"]);
    fireEvent.change(screen.getByLabelText("类型 1"), { target: { value: "int" } });
    expect(modes()).toEqual(["枚举值", "范围"]);
    fireEvent.change(screen.getByLabelText("类型 1"), { target: { value: "float" } });
    expect(modes()).toEqual(["枚举值", "范围"]);
    // 两种约束互斥：范围不显示枚举值输入，枚举不显示上下限
    expect(screen.getByLabelText("枚举值 1 值 1")).toBeInTheDocument();
    expect(screen.queryByLabelText("最小值 1")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("约束方式 1"), { target: { value: "range" } });
    expect(screen.queryByLabelText("枚举值 1 值 1")).not.toBeInTheDocument();
    expect(screen.getByLabelText("最小值 1")).toBeInTheDocument();
  });

  it("saves float ranges whose bounds may be equal or decimal", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    fireEvent.change(screen.getByLabelText("类型 1"), { target: { value: "float" } });
    fireEvent.change(screen.getByLabelText("约束方式 1"), { target: { value: "range" } });
    fireEvent.change(screen.getByLabelText("最小值 1"), { target: { value: "0.5" } });
    fireEvent.change(screen.getByLabelText("最大值 1"), { target: { value: "0.5" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([{
      machine_key: "label-1", display_name: "标签-1", value_type: "float", required: true,
      min_value: 0.5, max_value: 0.5,
    }], "annotation");
  });

  it("rejects duplicate enum values after type normalization", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    fireEvent.change(screen.getByLabelText("类型 1"), { target: { value: "int" } });
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "添加枚举值 1" }));
    fireEvent.change(screen.getByLabelText("枚举值 1 值 2"), { target: { value: "1.0" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(screen.getByRole("alert")).toHaveTextContent("枚举值不能重复");
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("枚举值 1 值 2"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([expect.objectContaining({ enum_values: [1, 2] })], "annotation");
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
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    // 范围缺最大值 → 拒绝
    fireEvent.change(screen.getByLabelText("约束方式 1"), { target: { value: "range" } });
    fireEvent.change(screen.getByLabelText("最小值 1"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(screen.getByRole("alert")).toHaveTextContent("必须同时填写最小值和最大值");
    // 整数范围不接受小数
    fireEvent.change(screen.getByLabelText("最大值 1"), { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(screen.getByRole("alert")).toHaveTextContent("整数");
    // 最小值不能大于最大值
    fireEvent.change(screen.getByLabelText("最大值 1"), { target: { value: "-1" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(screen.getByRole("alert")).toHaveTextContent("最小值不能大于最大值");
    expect(onSave).not.toHaveBeenCalled();
    // 补全后通过，且不再携带枚举值
    fireEvent.change(screen.getByLabelText("最大值 1"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([{ machine_key: "label-1", display_name: "标签-1", value_type: "int", required: true, min_value: 0, max_value: 10 }], "annotation");
  });

  it("offers range constraints for numeric annotation columns and saves them without enums", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    fireEvent.change(screen.getByLabelText("类型 1"), { target: { value: "int" } });
    fireEvent.change(screen.getByLabelText("约束方式 1"), { target: { value: "range" } });
    // 范围约束不需要枚举值：标注员在上下限内自行填写
    expect(screen.queryByLabelText("枚举值 1 值 1")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("最小值 1"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("最大值 1"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([{
      machine_key: "label-1", display_name: "标签-1", value_type: "int", required: true,
      min_value: 0, max_value: 10,
    }], "annotation");
  });

  it("keeps focus in the label name input while typing changes the machine key", () => {
    render(<LabelSchemaEditor onSave={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    const input = screen.getByLabelText("标签名称 1");
    input.focus();
    // 逐字输入：每个字符都会重新生成机器键，输入框不能因此被重挂
    fireEvent.change(input, { target: { value: "质" } });
    expect(screen.getByText("质")).toBeInTheDocument();
    expect(screen.getByLabelText("标签名称 1")).toBe(input);
    expect(document.activeElement).toBe(input);
    fireEvent.change(input, { target: { value: "质量" } });
    expect(screen.getByText("质量")).toBeInTheDocument();
    expect(document.activeElement).toBe(input);
  });

  it("resets a ranged column to enum when its type switches to string", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "添加列" }));
    fireEvent.change(screen.getByLabelText("类型 1"), { target: { value: "int" } });
    fireEvent.change(screen.getByLabelText("约束方式 1"), { target: { value: "range" } });
    fireEvent.change(screen.getByLabelText("最小值 1"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("类型 1"), { target: { value: "float" } });
    // 数值类型之间切换保留约束方式，仅清空旧值
    expect(screen.getByLabelText("约束方式 1")).toHaveValue("range");
    expect(screen.getByLabelText("最小值 1")).toHaveValue(null);
    fireEvent.change(screen.getByLabelText("类型 1"), { target: { value: "string" } });
    expect(screen.getByLabelText("约束方式 1")).toHaveValue("enum");
    fireEvent.change(screen.getByLabelText("枚举值 1 值 1"), { target: { value: "ok" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([{ machine_key: "label-1", display_name: "标签-1", value_type: "string", required: true, enum_values: ["ok"] }], "annotation");
  });

  it("restores the constraint mode of saved columns when remounted", () => {
    const onSave = vi.fn();
    render(<LabelSchemaEditor onSave={onSave} initialColumns={[
      { machine_key: "grade", display_name: "等级", value_type: "int", required: true, enum_values: [0, 1] },
      { machine_key: "score", display_name: "分数", value_type: "float", required: true, min_value: 0, max_value: 1 },
    ]} />);
    expect(screen.getByLabelText("约束方式 1")).toHaveValue("enum");
    expect(screen.getByLabelText("枚举值 1 值 2")).toHaveValue(1);
    expect(screen.getByLabelText("约束方式 2")).toHaveValue("range");
    expect(screen.getByLabelText("最大值 2")).toHaveValue(1);
    fireEvent.click(screen.getByRole("button", { name: "保存 schema" }));
    expect(onSave).toHaveBeenCalledWith([
      { machine_key: "grade", display_name: "等级", value_type: "int", required: true, enum_values: [0, 1] },
      { machine_key: "score", display_name: "分数", value_type: "float", required: true, min_value: 0, max_value: 1 },
    ], "annotation");
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

  it("prefills default columns from the model contract and falls back to one blank column", () => {
    expect(defaultLabelColumns([])).toEqual([expect.objectContaining({ machine_key: "label-1", constraint_mode: "enum" })]);
    expect(defaultLabelColumns([
      { machine_key: "fault", display_name: "故障", value_type: "int", enum_values: [0, 1] },
      { machine_key: "score", display_name: "分数", value_type: "float" },
    ])).toEqual([
      { machine_key: "fault", display_name: "故障", value_type: "int", required: true, isDefault: true, enum_values: [0, 1] },
      { machine_key: "score", display_name: "分数", value_type: "float", required: true, isDefault: true },
    ]);
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
