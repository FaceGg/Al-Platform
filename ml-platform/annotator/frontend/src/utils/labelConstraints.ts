import { LabelColumn } from '../api/tasks'

/** 自由填写的数值列的约束范围提示（范围含上下限）；枚举列直接列出可选值，无上下限时无需提示 */
export function rangeHint(column: LabelColumn): string {
  if (column.value_type === 'string' || column.enum_values?.length) return ''
  if (column.min_value == null && column.max_value == null) return ''
  const kind = column.value_type === 'int' ? '整数' : '数值'
  return `允许范围 ${column.min_value ?? '-∞'} ~ ${column.max_value ?? '+∞'}（含边界，${kind}）`
}
