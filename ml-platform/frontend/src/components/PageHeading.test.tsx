import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { translations } from "../i18n";
import PageHeading, { NAV_FALLBACK, navTitle } from "./PageHeading";

describe("PageHeading", () => {
  it("keeps the menu-name fallback table in sync with the i18n nav labels", () => {
    const zhNav = translations.zh.nav as Record<string, string>;
    const enNav = translations.en.nav as Record<string, string>;
    for (const [key, value] of Object.entries(NAV_FALLBACK)) {
      if (key in zhNav) expect(value.zh, `zh nav.${key}`).toBe(zhNav[key]);
      if (key in enNav) expect(value.en, `en nav.${key}`).toBe(enNav[key]);
    }
  });

  it("renders the unified section/page title from a nav key", () => {
    render(<PageHeading section="admin" navKey="users" />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("系统管理/用户管理");
  });

  it("renders a static title with description and actions", () => {
    render(
      <PageHeading
        section="infra"
        title="集群总览"
        desc="运行时总览"
        actions={<button type="button">刷新</button>}
      />,
    );
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("基础设施/集群总览");
    expect(screen.getByText("运行时总览")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "刷新" })).toBeInTheDocument();
  });

  it("falls back to the built-in menu names when t.nav is unavailable", () => {
    expect(navTitle(undefined, "orchestration", true)).toBe("应用编排");
    expect(navTitle({}, "demo_loop", false)).toBe("Closed-Loop Automation");
    expect(navTitle({ nav: { automl: "AutoML*" } }, "automl", true)).toBe("AutoML*");
  });
});
