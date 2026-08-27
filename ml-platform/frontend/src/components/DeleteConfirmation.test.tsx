import { fireEvent, render, screen, within } from "@testing-library/react";
import { App as AntApp, Button } from "antd";
import { describe, expect, it, vi } from "vitest";

import DeleteConfirmation from "./DeleteConfirmation";

describe("DeleteConfirmation", () => {
  it("confirms a row delete through the shared danger popup", async () => {
    const onConfirm = vi.fn();
    render(<AntApp><DeleteConfirmation label="删除任务 A" targetName="任务 A" onConfirm={onConfirm} /></AntApp>);

    fireEvent.click(screen.getByRole("button", { name: "删除任务 A" }));
    expect(await screen.findByText("确认删除？")).toBeInTheDocument();
    expect(document.querySelector(".delete-confirmation__overlay")).toBeInTheDocument();
    expect(screen.getByText("确定删除“任务 A”吗？删除后无法恢复。")).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("tooltip")).getByRole("button", { name: /取\s*消/ }));
    expect(onConfirm).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "删除任务 A" }));
    fireEvent.click(within(await screen.findByRole("tooltip")).getByRole("button", { name: /删\s*除/ }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("supports a batch trigger and selected count", async () => {
    const onConfirm = vi.fn();
    render(
      <AntApp>
        <DeleteConfirmation label="批量删除" selectedCount={3} onConfirm={onConfirm}>
          <Button danger>批量删除</Button>
        </DeleteConfirmation>
      </AntApp>,
    );

    fireEvent.click(screen.getByRole("button", { name: "批量删除" }));
    expect(await screen.findByText("确定删除选中的 3 项吗？删除后无法恢复。")).toBeInTheDocument();
  });

  it("does not open when disabled", () => {
    render(<AntApp><DeleteConfirmation label="删除任务 A" targetName="任务 A" disabled onConfirm={vi.fn()} /></AntApp>);

    fireEvent.click(screen.getByRole("button", { name: "删除任务 A" }));
    expect(screen.queryByText("确认删除？")).not.toBeInTheDocument();
  });
});
