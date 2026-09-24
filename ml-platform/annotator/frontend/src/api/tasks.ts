import { request } from './client'
import { createUuid } from '../utils/uuid'

export type Task = {
  id: string
  assignment_id?: string
  title: string
  status: string
  state?: string
  due_at?: string
  completed_samples?: number
  total_samples?: number
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
export type SampleFilters = {
  sample_search?: string
  label_status?: 'complete' | 'incomplete'
  comment_status?: 'open' | 'resolved' | 'none'
  modified_after?: string
  authorized_field?: string
  authorized_value?: string
}

export type TaskQueueQuery = {
  cursor?: string
  limit?: number
  search?: string
  status?: string
  assignment_state?: string
  sort?: 'created_at' | 'due_at' | 'status' | 'assignment_state'
  direction?: 'asc' | 'desc'
}

export const listTasks = (query: TaskQueueQuery = {}) =>
  request<{ items: Task[]; total: number; next_cursor?: string | null }>('/portal/tasks', {
    query: { limit: 50, ...query },
  })
export const getTask = (id: string, assignmentId?: string) => request<Task>(`/portal/tasks/${id}`, { query: { assignment_id: assignmentId } })
export const listSamples = (id: string, cursor?: string, assignmentId?: string, filters: SampleFilters = {}, offset = 0) =>
  request<{ items: Sample[]; next_cursor?: string }>(`/portal/tasks/${id}/samples`, {
    query: { cursor, limit: 50, offset, assignment_id: assignmentId, ...filters },
  })
export const saveLabels = (
  taskId: string,
  sampleId: string,
  values: Record<string, unknown>,
  baseRevision: number,
  assignmentId?: string,
) =>
  request<{ values: Record<string, unknown>; revision: number; task_revision?: number }>(`/portal/tasks/${taskId}/samples/${sampleId}/labels`, {
    method: 'PUT',
    query: { assignment_id: assignmentId },
    body: JSON.stringify({ values, base_revision: baseRevision }),
  })
export const bulkLabels = (taskId: string, items: Array<Record<string, unknown>>, assignmentId?: string) =>
  request<{ items: Array<{ sample_id: string; values: Record<string, unknown>; revision: number }> }>(`/portal/tasks/${taskId}/bulk-labels`, {
    method: 'POST',
    body: JSON.stringify({ items }),
    query: { assignment_id: assignmentId },
  })
export const confirmTask = (taskId: string, taskRevision: number, scopeHash: string, assignmentId?: string) =>
  request(`/portal/tasks/${taskId}/confirm`, {
    method: 'POST',
    body: JSON.stringify({ task_revision: taskRevision, scope_hash: scopeHash }),
    query: { assignment_id: assignmentId },
  })
export const editForReturn = (taskId: string, taskRevision: number, scopeHash: string, assignmentId?: string) =>
  request(`/portal/tasks/${taskId}/edit-for-return`, {
    method: 'POST',
    body: JSON.stringify({ task_revision: taskRevision, scope_hash: scopeHash }),
    query: { assignment_id: assignmentId },
  })
export const returnTask = (taskId: string, taskRevision: number, scopeHash: string, assignmentId?: string) =>
  request(`/portal/tasks/${taskId}/return`, {
    method: 'POST',
    headers: { 'Idempotency-Key': createUuid() },
    body: JSON.stringify({ task_revision: taskRevision, scope_hash: scopeHash }),
    query: { assignment_id: assignmentId },
  })
