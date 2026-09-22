import { useState } from "react";

export type LabelColumnDraft = {
  machine_key: string;
  display_name: string;
  value_type: "int" | "float" | "string";
  required: boolean;
  max_length?: number;
  enum_values?: Array<number | string>;
  min_value?: number;
  max_value?: number;
  instruction?: string;
  /** UI 态：当前选择的约束方式；未设置时按已有约束值推导（回显已保存 schema 用） */
  constraint_mode?: "enum" | "range" | "enum_range";
  /** UI 态：由模型输出契约预填的默认列——可修改但不可删除（至少保留一个标签列） */
  isDefault?: boolean;
};

type ConstraintMode = "enum" | "range" | "enum_range";

type Props = {
  initialColumns?: LabelColumnDraft[];
  initialPurpose?: "annotation" | "training" | "inference";
  /** 向导蓝框等场景隐藏「用途」选择（固定 annotation）；默认展示 */
  showPurpose?: boolean;
  onSave: (columns: LabelColumnDraft[], purpose: "annotation" | "training" | "inference") => void;
};

function createColumn(index: number): LabelColumnDraft {
  return {
    machine_key: `label-${index}`,
    display_name: `标签-${index}`,
    value_type: "string",
    required: true,
    constraint_mode: "enum",
    enum_values: [""],
  };
}

function nextColumnIndex(columns: LabelColumnDraft[]): number {
  const used = new Set(columns.map((column) => column.machine_key));
  let index = columns.length + 1;
  while (used.has(`label-${index}`)) index += 1;
  return index;
}

function constraintMode(column: LabelColumnDraft): ConstraintMode {
  // 约束方式必选且默认枚举值：无「无约束」选项，旧数据回显时兜底为枚举值
  if (column.constraint_mode) return column.constraint_mode;
  const hasRange = column.min_value !== undefined || column.max_value !== undefined;
  return hasRange ? "range" : "enum";
}

/** 校验单个枚举值文本与所选类型匹配且非空 */
function validEnumValue(raw: string, value_type: LabelColumnDraft["value_type"]): boolean {
  if (!raw.trim()) return false;
  if (value_type === "string") return true;
  const numeric = Number(raw);
  if (!Number.isFinite(numeric)) return false;
  if (value_type === "int" && !Number.isInteger(numeric)) return false;
  return true;
}

export default function LabelSchemaEditor({ initialColumns = [], initialPurpose = "annotation", showPurpose = true, onSave }: Props) {
  const [columns, setColumns] = useState<LabelColumnDraft[]>(initialColumns);
  const [purpose, setPurpose] = useState<"annotation" | "training" | "inference">(initialPurpose);
  const [error, setError] = useState("");
  const add = () => setColumns((items) => [...items, createColumn(nextColumnIndex(items))]);
  const update = (index: number, patch: Partial<LabelColumnDraft>) => setColumns((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  const save = () => {
    const keys = columns.map((column) => column.machine_key.trim());
    if (new Set(keys).size !== keys.length || columns.some((column) => !column.display_name.trim())) {
      setError("机器键必须唯一，标签名称不能为空");
      return;
    }
    for (let index = 0; index < columns.length; index += 1) {
      const column = columns[index];
      const mode = constraintMode(column);
      const label = column.display_name.trim() || `第 ${index + 1} 列`;
      if (mode === "enum" || mode === "enum_range") {
        const values = (column.enum_values || []).map((value) => String(value));
        if (!values.length || values.some((value) => !validEnumValue(value, column.value_type))) {
          setError(`「${label}」的枚举值不能为空，且必须与所选类型（${column.value_type === "int" ? "整数" : column.value_type === "float" ? "浮点数" : "字符串"}）匹配`);
          return;
        }
      }
      if (mode === "range" || mode === "enum_range") {
        const { min_value, max_value } = column;
        if (min_value === undefined || min_value === null || max_value === undefined || max_value === null
          || !Number.isFinite(min_value) || !Number.isFinite(max_value)
          || (column.value_type === "int" && (!Number.isInteger(min_value) || !Number.isInteger(max_value)))) {
          setError(`「${label}」的范围不能为空，且必须与所选类型（${column.value_type === "int" ? "整数" : "浮点数"}）匹配`);
          return;
        }
        if (min_value > max_value) {
          setError(`「${label}」的最小值不能大于最大值`);
          return;
        }
      }
    }
    setError("");
    onSave(columns.map((column) => {
      const mode = constraintMode(column);
      const normalized: LabelColumnDraft = {
        machine_key: column.machine_key.trim(),
        display_name: column.display_name.trim(),
        value_type: column.value_type,
        // 向导中标签列默认必填，不再提供选填开关；字符串长度由后端 65536 上限兜底，无需用户填写
        required: true,
      };
      if (mode === "enum" || mode === "enum_range") {
        normalized.enum_values = (column.enum_values || []).map((value) => column.value_type === "string" ? String(value).trim() : Number(value));
      }
      if (mode === "range" || mode === "enum_range") {
        normalized.min_value = column.min_value;
        normalized.max_value = column.max_value;
      }
      if (column.instruction?.trim()) normalized.instruction = column.instruction.trim();
      return normalized;
    }), purpose);
  };
  return <section className="label-schema-editor" aria-label="标签 schema 编辑器">
    <div className="label-schema-editor__toolbar">
      <h3 className="label-schema-editor__title">标签列定义</h3>
      <div className="label-schema-editor__toolbar-actions">
        {showPurpose && <label className="label-schema-editor__purpose">用途<select aria-label="schema 用途" value={purpose} onChange={(event) => setPurpose(event.target.value as typeof purpose)}><option value="annotation">标注</option><option value="training">训练</option><option value="inference">推理</option></select></label>}
        <button type="button" className="ant-btn ant-btn-sm" onClick={add}>添加列</button>
        <button type="button" className="ant-btn ant-btn-primary ant-btn-sm" onClick={save} disabled={!columns.length}>保存 schema</button>
      </div>
    </div>
    {error && <p className="label-schema-editor__error" role="alert">{error}</p>}
    {columns.map((column, index) => {
      const mode = constraintMode(column);
      const enumValues = column.enum_values?.length ? column.enum_values.map(String) : [""];
      const removable = !column.isDefault && columns.length > 1;
      return <div className="label-schema-editor__card" key={`${column.machine_key}-${index}`}>
      <div className="label-schema-editor__card-head">
        {/* 机器键 label-N 自动递增，只读不可修改；与标签名称同行 */}
        <div className="label-schema-editor__identity">
          <span className="label-schema-editor__machine-key" aria-label={`机器键 ${index + 1}`}>{column.machine_key}</span>
          <input className="label-schema-editor__name-input" aria-label={`标签名称 ${index + 1}`} value={column.display_name} onChange={(event) => update(index, { display_name: event.target.value })} placeholder="标签名称" />
        </div>
        {removable && <button type="button" className="ant-btn ant-btn-sm ant-btn-danger" aria-label={`删除列 ${index + 1}`} onClick={() => setColumns((items) => items.filter((_, itemIndex) => itemIndex !== index))}>删除</button>}
      </div>
      <div className="label-schema-editor__grid label-schema-editor__grid--pair">
        <div className="label-schema-editor__field">
          <label>值类型</label>
          <select aria-label={`类型 ${index + 1}`} value={column.value_type} onChange={(event) => {
            const value_type = event.target.value as LabelColumnDraft["value_type"];
            // 切换类型后清空约束值（类型不匹配的旧值失效），保留当前约束方式
            update(index, { value_type, enum_values: [""], min_value: undefined, max_value: undefined });
          }}>
            <option value="string">字符串</option><option value="int">整数</option><option value="float">浮点数</option>
          </select>
        </div>
        <div className="label-schema-editor__field">
          <label>约束方式</label>
          <select aria-label={`约束方式 ${index + 1}`} value={mode} onChange={(event) => {
            const next = event.target.value as ConstraintMode;
            update(index, {
              constraint_mode: next,
              enum_values: next === "enum" || next === "enum_range" ? (column.enum_values?.length ? column.enum_values : [""]) : [],
              min_value: next === "range" || next === "enum_range" ? column.min_value : undefined,
              max_value: next === "range" || next === "enum_range" ? column.max_value : undefined,
            });
          }}>
            <option value="enum">枚举值</option>
            {column.value_type !== "string" && <option value="range">范围</option>}
            {column.value_type !== "string" && <option value="enum_range">枚举值且范围</option>}
          </select>
        </div>
      </div>
      {(mode === "enum" || mode === "enum_range") && <div className="label-schema-editor__field">
        <label>枚举值 <span className="label-schema-editor__hint">点击 + 逐个添加；值须与所选类型匹配，不能为空</span></label>
        <div className="label-schema-editor__enum" aria-label={`枚举值 ${index + 1}`}>
          {enumValues.map((value, valueIndex) => <div className="label-schema-editor__enum-row" key={valueIndex}>
            <input
              aria-label={`枚举值 ${index + 1} 值 ${valueIndex + 1}`}
              type={column.value_type === "string" ? "text" : "number"}
              step={column.value_type === "float" ? "any" : "1"}
              value={value}
              onChange={(event) => update(index, { enum_values: enumValues.map((item, itemIndex) => itemIndex === valueIndex ? event.target.value : item) })}
            />
            {enumValues.length > 1 && <button type="button" className="ant-btn ant-btn-sm" aria-label={`删除枚举值 ${index + 1} 值 ${valueIndex + 1}`} onClick={() => update(index, { enum_values: enumValues.filter((_, itemIndex) => itemIndex !== valueIndex) })}>删除</button>}
          </div>)}
          <button type="button" className="ant-btn ant-btn-sm label-schema-editor__enum-add" aria-label={`添加枚举值 ${index + 1}`} onClick={() => update(index, { enum_values: [...enumValues, ""] })}>+</button>
        </div>
      </div>}
      {(mode === "range" || mode === "enum_range") && column.value_type !== "string" && <div className="label-schema-editor__grid label-schema-editor__grid--half">
        <div className="label-schema-editor__field">
          <label>最小值</label>
          <input aria-label={`最小值 ${index + 1}`} type="number" step={column.value_type === "float" ? "any" : "1"} value={column.min_value ?? ""} onChange={(event) => update(index, { min_value: event.target.value !== "" ? Number(event.target.value) : undefined })} placeholder="最小值" />
        </div>
        <div className="label-schema-editor__field">
          <label>最大值</label>
          <input aria-label={`最大值 ${index + 1}`} type="number" step={column.value_type === "float" ? "any" : "1"} value={column.max_value ?? ""} onChange={(event) => update(index, { max_value: event.target.value !== "" ? Number(event.target.value) : undefined })} placeholder="最大值" />
        </div>
      </div>}
      <div className="label-schema-editor__field">
        <label>列说明 <span className="label-schema-editor__hint">选填，展示给标注员的填写指引</span></label>
        <input aria-label={`列说明 ${index + 1}`} value={column.instruction ?? ""} onChange={(event) => update(index, { instruction: event.target.value })} placeholder="列级标注说明" />
      </div>
    </div>;
    })}
  </section>;
}
