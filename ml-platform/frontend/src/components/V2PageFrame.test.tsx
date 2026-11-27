import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import V2PageFrame from "./V2PageFrame";
import PageHeading from "./PageHeading";

/** V2PageFrame 标题防重：children 里已有 PageHeading 时不再渲染框架级标题
 *（2026-11-27 用户实测：质量管理板块 20 页双重标题）。 */

function renderFrame(node: React.ReactElement) {
  return render(<MemoryRouter initialEntries={["/"]}>{node}</MemoryRouter>);
}

describe("V2PageFrame 标题防重", () => {
  it("children 无 PageHeading：渲染框架级标题（正确形态）", () => {
    renderFrame(
      <V2PageFrame section="algo" navKey="automl">
        <div>内容区</div>
      </V2PageFrame>,
    );
    expect(screen.getAllByRole("heading", { level: 2 }).length).toBe(1);
    expect(screen.getByText("内容区")).toBeInTheDocument();
  });

  it("children 自渲染 PageHeading：不重复渲染（兼容历史页面）", () => {
    renderFrame(
      <V2PageFrame section="quality" navKey="quality_dashboard">
        <PageHeading section="quality" navKey="quality_dashboard" desc="描述" />
        <div>内容区</div>
      </V2PageFrame>,
    );
    expect(screen.getAllByRole("heading", { level: 2 }).length).toBe(1);
    expect(screen.getByText("内容区")).toBeInTheDocument();
  });
});
