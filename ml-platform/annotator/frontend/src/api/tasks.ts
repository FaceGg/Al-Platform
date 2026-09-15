import { request } from './client'

export type Task = {
  id: string
  title: string
  status: string
  due_at?: string
  task_revision: number
  read_only?: boolean
  scope_hash: string
  samples?: Sample[]
  instructions?: string
  visible_columns?: string[]
  label_schema?: LabelSchema
}
export type LabelColumn = {
  machine_key: string
  display_name?: string
  value_type: 'int' | 'float' | 'string'
  required?: boolean
  enum_values?: Array<string | number>
  min_value?: number
  max_value?: number
  max_length?: number
}
export type LabelSchema = { columns: LabelColumn[] }
export type Sample = {
  sample_id: string
  values: Record<string, unknown>
  labels: Record<string, unknown>
  revision: number
}

export const listTasks = () => request<{ items: Task[] }>('/portal/tasks')
export const getTask = (id: string) => request<Task>(`/portal/tasks/${id}`)
export const listSamples = (id: string, cursor?: string) =>
  request<{ items: Sample[]; next_cursor?: string }>(`/portal/tasks/${id}/samples`, {
    query: { cursor, limit: 50 },
  })
export const saveLabels = (
  taskId: string,
  sampleId: string,
  values: Record<string, unknown>,
  baseRevision: number,
) =>
  request<{ values: Record<string, unknown>; revision: number; task_revision?: number }>(`/portal/tasks/${taskId}/samples/${sampleId}/labels`, {
    method: 'PUT',
    body: JSON.stringify({ values, base_revision: baseRevision }),
  })
export const bulkLabels = (taskId: string, items: Array<Record<string, unknown>>) =>
  request(`/portal/tasks/${taskId}/bulk-labels`, {
    method: 'POST',
    body: JSON.stringify({ items }),
  })
export const confirmTask = (taskId: string, taskRevision: number, scopeHash: string) =>
  request(`/portal/tasks/${taskId}/confirm`, {
    method: 'POST',
    body: JSON.stringify({ task_revision: taskRevision, scope_hash: scopeHash }),
  })
export const editForReturn = (taskId: string, taskRevision: number, scopeHash: string) =>
  request(`/portal/tasks/${taskId}/edit-for-return`, {
    method: 'POST',
    body: JSON.stringify({ task_revision: taskRevision, scope_hash: scopeHash }),
  })
export const returnTask = (taskId: string, taskRevision: number, scopeHash: string) =>
  request(`/portal/tasks/${taskId}/return`, {
    method: 'POST',
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify({ task_revision: taskRevision, scope_hash: scopeHash }),
  })
