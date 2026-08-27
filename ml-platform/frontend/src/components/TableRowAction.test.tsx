import { fireEvent, render, screen } from "@testing-library/react";
import { DeleteOutlined, EyeOutlined } from "@ant-design/icons";
import { App as AntApp } from "antd";
import { describe, expect, it, vi } from "vitest";

import TableRowAction from "./TableRowAction";

describe("TableRowAction", () => {
  it("renders a fixed icon-only action with an accessible tooltip", async () => {
    const onClick = vi.fn();
    render(
      <AntApp>
        <TableRowAction label="查看项目" icon={<EyeOutlined />} onClick={onClick} />
      </AntApp>,
    );

    const button = screen.getByRole("button", { name: "查看项目" });
    expect(button).toHaveClass("table-row-action");
    expect(button).not.toHaveTextContent("查看项目");
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);

    fireEvent.mouseEnter(button.parentElement!);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("查看项目");
  });

  it("applies the danger treatment to delete actions", () => {
    render(
      <AntApp>
        <TableRowAction label="删除项目" icon={<DeleteOutlined />} danger />
      </AntApp>,
    );

    expect(screen.getByRole("button", { name: "删除项目" })).toHaveClass("table-row-action--danger");
  });

  it("keeps disabled actions labelled and non-interactive", () => {
    render(
      <AntApp>
        <TableRowAction label="停止任务" icon={<DeleteOutlined />} disabled />
      </AntApp>,
    );

    expect(screen.getByRole("button", { name: "停止任务" })).toBeDisabled();
  });
});
