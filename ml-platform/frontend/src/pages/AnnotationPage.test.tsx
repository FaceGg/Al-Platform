import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AnnotationPage from "./AnnotationPage";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), remove: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../components/AnnotationCanvas", () => ({ default: () => null }));
vi.mock("../api/client", () => ({ apiGet: api.get, apiPost: api.post, apiPut: api.put, apiDelete: api.remove }));
vi.mock("../i18n", () => ({ useI18n: () => ({ lang: "zh", t: { common: { delete: "删除", cancel: "取消" } } }) }));

describe("AnnotationPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockResolvedValue({ items: [{ id: "task-1", name: "焊缝标注", status: "pending", total_samples: 0, labeled_samples: 0, reviewed_samples: 0 }] });
    api.remove.mockResolvedValue(undefined);
  });

  it("deletes a legacy annotation task only after confirmation", async () => {
    render(<AntApp><AnnotationPage /></AntApp>);

    fireEvent.click(await screen.findByRole("button", { name: "删除标注任务 焊缝标注" }));
    expect(api.remove).not.toHaveBeenCalled();
    fireEvent.click(within(await screen.findByRole("tooltip")).getByRole("button", { name: /删\s*除/ }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith("/annotations/tasks/task-1"));
  });
});
