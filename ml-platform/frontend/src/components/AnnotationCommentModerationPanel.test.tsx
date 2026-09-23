import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import AnnotationCommentModerationPanel from "./AnnotationCommentModerationPanel";
import * as comments from "../api/annotationComments";

vi.mock("../api/annotationComments", () => ({
  listAnnotationComments: vi.fn(),
  updateAnnotationCommentStatus: vi.fn(),
}));

const first = { id: "c1", task_id: "t1", content: "first comment", status: "open" as const };

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(comments.listAnnotationComments).mockResolvedValue({
    items: [first], total: 2, next_cursor: "c1",
  });
});

it("loads subsequent pages and preserves comments after a failed request", async () => {
  render(<AnnotationCommentModerationPanel taskId="t1" open onClose={() => {}} />);
  await waitFor(() => expect(screen.getByText("first comment")).toBeVisible());
  await screen.findByRole("button", { name: "加载更多" });
  vi.mocked(comments.listAnnotationComments).mockRejectedValueOnce(new Error("offline"));
  fireEvent.click(screen.getByRole("button", { name: "加载更多" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("offline");
  expect(screen.getByText("first comment")).toBeVisible();
  expect(await screen.findByRole("button", { name: "加载更多" })).toBeEnabled();
  vi.mocked(comments.listAnnotationComments).mockResolvedValueOnce({
    items: [{ ...first, id: "c2", content: "second comment" }], total: 2, next_cursor: null,
  });
  fireEvent.click(screen.getByRole("button", { name: "加载更多" }));
  expect(await screen.findByText("second comment")).toBeVisible();
  expect(screen.getByText("first comment")).toBeVisible();
  expect(comments.listAnnotationComments).toHaveBeenLastCalledWith("t1", expect.objectContaining({ cursor: "c1" }));
});

it("resets pagination when filtering by sample", async () => {
  const view = render(<AnnotationCommentModerationPanel taskId="t1" open onClose={() => {}} />);
  await screen.findByText("first comment");
  fireEvent.change(screen.getByPlaceholderText("样本 ID"), { target: { value: "s1" } });
  fireEvent.keyDown(screen.getByPlaceholderText("样本 ID"), { key: "Enter", code: "Enter", charCode: 13 });
  await waitFor(() => expect(comments.listAnnotationComments).toHaveBeenLastCalledWith("t1", expect.objectContaining({ sample_id: "s1", cursor: undefined })));
  view.rerender(<AnnotationCommentModerationPanel taskId="t2" open onClose={() => {}} />);
  await waitFor(() => expect(comments.listAnnotationComments).toHaveBeenLastCalledWith("t2", expect.objectContaining({ cursor: undefined })));
});

it("ignores a pending response after switching tasks", async () => {
  let resolveOld!: (page: comments.CommentPage) => void;
  vi.mocked(comments.listAnnotationComments).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
  const view = render(<AnnotationCommentModerationPanel taskId="t1" open onClose={() => {}} />);
  vi.mocked(comments.listAnnotationComments).mockResolvedValueOnce({
    items: [{ ...first, id: "new", task_id: "t2", content: "new task" }], total: 1, next_cursor: null,
  });
  view.rerender(<AnnotationCommentModerationPanel taskId="t2" open onClose={() => {}} />);
  await screen.findByText("new task");
  await act(async () => { resolveOld({ items: [first], total: 1, next_cursor: null }); });
  expect(screen.queryByText("first comment")).not.toBeInTheDocument();
  expect(screen.getByText("new task")).toBeInTheDocument();
});
