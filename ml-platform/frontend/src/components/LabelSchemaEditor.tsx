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
};

type Props = {
  initialColumns?: LabelColumnDraft[];
  onSave: (columns: LabelColumnDraft[]) => void;
};

export default function LabelSchemaEditor({ initialColumns = [], onSave }: Props) {
  const [columns, setColumns] = useState<LabelColumnDraft[]>(initialColumns);
  const [error, setError] = useState("");
  const add = () => setColumns((items) => [...items, {
    machine_key: `label_${items.length + 1}`,
    display_name: `标签 ${items.length + 1}`,
    value_type: "string",
    required: false,
  }]);
  const update = (index: number, patch: Partial<LabelColumnDraft>) => setColumns((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  const save = () => {
    const keys = columns.map((column) => column.machine_key.trim());
    const invalidConstraints = columns.some((column) =>
      (column.enum_values || []).some((value) => column.value_type !== "string" && !Number.isFinite(value))
      || (column.value_type === "int" && (column.enum_values || []).some((value) => !Number.isInteger(value)))
      || (column.min_value !== undefined && column.max_value !== undefined && column.min_value > column.max_value)
    );
    if (keys.some((key) => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) || new Set(keys).size !== keys.length || columns.some((column) => !column.display_name.trim()) || invalidConstraints) {
      setError("机器键必须唯一且符合标识符格式，显示名称不能为空");
      return;
    }
    setError("");
    onSave(columns.map((column) => {
      const normalized: LabelColumnDraft = {
        machine_key: column.machine_key.trim(),
        display_name: column.display_name.trim(),
        value_type: column.value_type,
        required: column.required,
      };
      if (column.enum_values?.length) normalized.enum_values = column.enum_values;
      if (column.value_type === "string" && column.max_length !== undefined) normalized.max_length = column.max_length;
      if (column.value_type !== "string" && column.min_value !== undefined) normalized.min_value = column.min_value;
      if (column.value_type !== "string" && column.max_value !== undefined) normalized.max_value = column.max_value;
      return normalized;
    }));
  };
  return <section aria-label="标签 schema 编辑器">
    <div className="label-schema-editor__toolbar"><button type="button" onClick={add}>添加列</button><button type="button" onClick={save} disabled={!columns.length}>保存 schema</button></div>
    {error && <p role="alert">{error}</p>}
    {columns.map((column, index) => <div className="label-schema-editor__row" key={`${column.machine_key}-${index}`}>
      <input aria-label={`机器键 ${index + 1}`} value={column.machine_key} onChange={(event) => update(index, { machine_key: event.target.value })} />
      <input aria-label={`显示名称 ${index + 1}`} value={column.display_name} onChange={(event) => update(index, { display_name: event.target.value })} />
      <select aria-label={`类型 ${index + 1}`} value={column.value_type} onChange={(event) => {
        const value_type = event.target.value as LabelColumnDraft["value_type"];
        update(index, value_type === "string"
          ? { value_type, min_value: undefined, max_value: undefined, enum_values: [] }
          : { value_type, max_length: undefined, enum_values: [] });
      }}>
        <option value="string">字符串</option><option value="int">整数</option><option value="float">浮点数</option>
      </select>
      <label><input type="checkbox" checked={column.required} onChange={(event) => update(index, { required: event.target.checked })} />必填</label>
      {column.value_type === "string" && <input aria-label={`最大字节数 ${index + 1}`} type="number" min={1} value={column.max_length ?? ""} onChange={(event) => update(index, { max_length: event.target.value ? Number(event.target.value) : undefined })} placeholder="最大字节数" />}
      <input aria-label={`枚举值 ${index + 1}`} value={(column.enum_values || []).join(", " )} onChange={(event) => {
        const values = event.target.value.split(",").map((value) => value.trim()).filter(Boolean);
        update(index, { enum_values: values.map((value) => column.value_type === "string" ? value : Number(value)) });
      }} placeholder="枚举值" />
      {column.value_type !== "string" && <>
        <input aria-label={`最小值 ${index + 1}`} type="number" value={column.min_value ?? ""} onChange={(event) => update(index, { min_value: event.target.value ? Number(event.target.value) : undefined })} placeholder="最小值" />
        <input aria-label={`最大值 ${index + 1}`} type="number" value={column.max_value ?? ""} onChange={(event) => update(index, { max_value: event.target.value ? Number(event.target.value) : undefined })} placeholder="最大值" />
      </>}
    </div>)}
  </section>;
}
