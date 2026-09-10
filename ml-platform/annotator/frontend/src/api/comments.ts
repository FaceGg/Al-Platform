import { request } from './client'
export const listComments = (taskId: string) => request<{ items: Array<{ id: string; content: string }> }>('/portal/comments', { query: { task_id: taskId } })
export const createComment = (taskId: string, content: string, sampleId?: string) => request('/portal/comments', { method: 'POST', body: JSON.stringify({ task_id: taskId, content, sample_id: sampleId }) })
