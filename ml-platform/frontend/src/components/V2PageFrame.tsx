import type { ReactNode } from "react";
import PageHeading, { type SectionId } from "./PageHeading";

/**
 * P3 v2 页面框架：把算法平台/基础设施/系统管理的既有 antd 页统一到
 * v2 深蓝科技风（设计稿 v2-shell.css 视觉体系）。
 *
 * 原则：只包壳不改逻辑——pagehead（「板块/页面名」标题+描述+操作位，
 * 统一由 PageHeading 渲染）+ v2-legacy 容器（CSS 级把 antd Card/Table/
 * Pagination/Button 对齐 v2 色板），页面内部 CRUD/表单/路由全部保留。
 */

export default function V2PageFrame({
  section,
  title,
  navKey,
  desc,
  actions,
  children,
  testId,
}: {
  section: SectionId;
  /** 静态页面名；菜单页优先用 navKey（页面名取侧栏菜单名真源）。 */
  title?: string;
  navKey?: string;
  desc?: string;
  actions?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <div className="v2-legacy" data-testid={testId}>
      <PageHeading section={section} title={title} navKey={navKey} desc={desc} actions={actions} />
      {children}
    </div>
  );
}
