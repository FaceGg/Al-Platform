import { request } from './client'
export type Comment = { id: string; content: string; sample_id?: string; parent_id?: string; status?: string; created_at?: string }
export const listComments = (taskId: string, cursor?: string, assignmentId?: string) =>
  request<{ items: Comment[]; next_cursor?: string | null }>('/portal/comments', {
    query: { task_id: taskId, cursor, assignment_id: assignmentId, limit: 200 },
  })
export const createComment = (taskId: string, content: string, sampleId?: string, assignmentId?: string, parentId?: string) =>
  request<Comment>('/portal/comments', {
    method: 'POST',
    body: JSON.stringify({ task_id: taskId, content, sample_id: sampleId, parent_id: parentId }),
    query: { assignment_id: assignmentId },
  })
