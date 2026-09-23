import apiClient from "./client";

export type AnnotationComment = {
  id: string;
  task_id: string;
  sample_id?: string | null;
  parent_id?: string | null;
  content: string;
  status: "open" | "resolved";
  related_revision?: number | null;
  resolved_by?: string | null;
  resolved_at?: string | null;
};

export type CommentPage = { items: AnnotationComment[]; total: number; next_cursor: string | null };
export type CommentFilters = {
  status?: "open" | "resolved";
  sample_id?: string;
  thread?: "all" | "roots" | "replies";
  cursor?: string;
};

export async function listAnnotationComments(taskId: string, filters: CommentFilters = {}): Promise<CommentPage> {
  const response = await apiClient.get("/annotation-comments", { params: { task_id: taskId, limit: 50, ...filters } });
  return response.data;
}

export async function updateAnnotationCommentStatus(
  commentId: string,
  status: "open" | "resolved",
): Promise<AnnotationComment> {
  const response = await apiClient.patch(`/annotation-comments/${encodeURIComponent(commentId)}/status`, { status });
  return response.data;
}
