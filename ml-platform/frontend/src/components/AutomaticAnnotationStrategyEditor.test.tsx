import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AutomaticAnnotationStrategyEditor, { createAutomaticStrategyDraft, typedAutomaticValue } from "./AutomaticAnnotationStrategyEditor";
import type { AnnotationOutputColumn } from "../api/models";

const enumColumn: AnnotationOutputColumn = { machine_key: "grade", display_name: "等级", value_type: "int", required: true, enum_values: [0, 1] };
const rangeColumn: AnnotationOutputColumn = { machine_key: "score", display_name: "分数", value_type: "float", required: true, min_value: 0.5, max_value: 1.5 };

function renderEditor(columns: AnnotationOutputColumn[], otherValues: Record<string, string> = {}) {
  const onChange = vi.fn();
  render(<AutomaticAnnotationStrategyEditor
    idPrefix="test"
    columns={columns}
    sourceColumns={[]}
    value={{ ...createAutomaticStrategyDraft(columns), otherValues }}
    onChange={onChange}
  />);
  return onChange;
}

describe("AutomaticAnnotationStrategyEditor label constraints", () => {
  it("only offers the defined values for enum columns", () => {
    const onChange = renderEditor([enumColumn]);
    const select = screen.getByRole("combobox", { name: "其他兜底值 等级" });
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual(["请选择", "0", "1"]);
    fireEvent.change(select, { target: { value: "1" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ otherValues: { grade: "1" } }));
  });

  it("keeps an imported value outside the enum visible instead of silently clearing it", () => {
    renderEditor([enumColumn], { grade: "9" });
    const select = screen.getByRole("combobox", { name: "其他兜底值 等级" });
    expect(select).toHaveValue("9");
    expect(within(select).getByRole("option", { name: "9（不在枚举值内）" })).toBeInTheDocument();
  });

  it("bounds free-form inputs for range columns", () => {
    renderEditor([rangeColumn]);
    const input = screen.getByRole("spinbutton", { name: "其他兜底值 分数" });
    expect(input).toHaveAttribute("min", "0.5");
    expect(input).toHaveAttribute("max", "1.5");
    expect(input).toHaveAttribute("placeholder", "0.5 ~ 1.5");
  });
});

describe("typedAutomaticValue", () => {
  it("accepts only defined enum values with the column type", () => {
    expect(typedAutomaticValue(enumColumn, "1")).toEqual({ value: 1 });
    expect(typedAutomaticValue(enumColumn, "2").error).toBe("等级 必须是已定义的枚举值");
    expect(typedAutomaticValue(enumColumn, "x").error).toBe("等级 必须是整数");
    const stringColumn: AnnotationOutputColumn = { machine_key: "quality", display_name: "质量", value_type: "string", required: true, enum_values: ["ok", "ng"] };
    expect(typedAutomaticValue(stringColumn, "ok")).toEqual({ value: "ok" });
    expect(typedAutomaticValue(stringColumn, "bad").error).toBe("质量 必须是已定义的枚举值");
  });

  it("treats range bounds as inclusive", () => {
    expect(typedAutomaticValue(rangeColumn, "0.5")).toEqual({ value: 0.5 });
    expect(typedAutomaticValue(rangeColumn, "1.5")).toEqual({ value: 1.5 });
    expect(typedAutomaticValue(rangeColumn, "0.4").error).toBe("分数 必须在 0.5 ~ 1.5 范围内");
    expect(typedAutomaticValue(rangeColumn, "1.6").error).toBe("分数 必须在 0.5 ~ 1.5 范围内");
    expect(typedAutomaticValue(rangeColumn, "abc").error).toBe("分数 必须是有限浮点数");
  });

  it("keeps unconstrained columns type-checked only", () => {
    const plain: AnnotationOutputColumn = { machine_key: "count", display_name: "数量", value_type: "int", required: true };
    expect(typedAutomaticValue(plain, "12")).toEqual({ value: 12 });
    expect(typedAutomaticValue(plain, "1.5").error).toBe("数量 必须是整数");
    expect(typedAutomaticValue({ ...plain, value_type: "string" }, " ").error).toBe("数量 不能为空");
  });
});
