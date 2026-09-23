import { request } from './client'
import { LabelSchema } from './tasks'

export type AdminTaskListItem = {
  id: string
  title: string
  status: string
  mode: string
  created_at: string | null
  task_revision: number
  pending_return_batch_id: string | null
  return_state: string | null
  sample_count: number
  completed_samples: number | null
  annotator_name: string | null
  project_name: string | null
}

export type AdminTask = {
  id: string
  title: string
  status: string
  mode: string
  created_at: string | null
  instructions: string
  visible_columns: string[]
  label_schema: LabelSchema
  sample_scope: { kind?: string; sample_count: number; scope_hash?: string }
  pending_return_batch_id: string | null
  return_state: string | null
  read_only: true
  task_revision: number
}

export type AdminSample = {
  sample_id: string
  values: Record<string, unknown>
  labels: Record<string, unknown>
  revision: number | null
}

export type AdminComment = {
  id: string
  task_id?: string
  sample_id: string
  parent_id: string | null
  author_name: string | null
  content: string
  status?: string | null
  created_at?: string | null
}

export type AdminTaskQuery = { cursor?: string; limit?: number; search?: string }

export const listAdminTasks = (query: AdminTaskQuery = {}) =>
  request<{ items: AdminTaskListItem[]; total: number; next_cursor: string | null }>('/portal/admin/tasks', {
    query: { limit: 50, ...query },
  })

export const getAdminTask = (taskId: string) => request<AdminTask>(`/portal/admin/tasks/${taskId}`)

export const listAdminSamples = (taskId: string, cursor?: string, sampleSearch?: string) =>
  request<{ items: AdminSample[]; total: number; next_cursor: string | null }>(`/portal/admin/tasks/${taskId}/samples`, {
    query: { cursor, limit: 50, sample_search: sampleSearch },
  })

export const listAdminComments = (taskId: string, sampleId?: string) =>
  request<{ items: AdminComment[]; total: number }>(`/portal/admin/tasks/${taskId}/comments`, {
    query: { sample_id: sampleId, limit: 200 },
  })

export const createAdminComment = (taskId: string, sampleId: string, content: string, parentId?: string) =>
  request<AdminComment>(`/portal/admin/tasks/${taskId}/comments`, {
    method: 'POST',
    body: JSON.stringify({ sample_id: sampleId, content, parent_id: parentId ?? null }),
  })

export const acceptAdminTask = (taskId: string) =>
  request<{ dataset_version_id: string; status: string; version: number }>(`/portal/admin/tasks/${taskId}/accept`, {
    method: 'POST',
  })

export const returnAdminTask = (taskId: string, reason: string) =>
  request<{ return_batch_id: string; state: string }>(`/portal/admin/tasks/${taskId}/return`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
