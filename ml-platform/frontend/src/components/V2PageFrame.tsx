import type { ReactNode } from "react";

/**
 * P3 v2 页面框架：把算法平台/基础设施/系统管理的既有 antd 页统一到
 * v2 深蓝科技风（设计稿 v2-shell.css 视觉体系）。
 *
 * 原则：只包壳不改逻辑——pagehead（标题+描述+操作位）+ v2-legacy 容器
 * （CSS 级把 antd Card/Table/Pagination/Button 对齐 v2 色板），
 * 页面内部 CRUD/表单/路由全部保留。
 */

export default function V2PageFrame({
  title,
  desc,
  actions,
  children,
  testId,
}: {
  title: string;
  desc?: string;
  actions?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <div className="v2-legacy" data-testid={testId}>
      <div className="v2-pagehead">
        <div>
          <h2 className="v2-pt">{title}</h2>
          {desc ? <p className="v2-pdesc">{desc}</p> : null}
        </div>
        {actions ? <div className="v2-pagehead-actions">{actions}</div> : null}
      </div>
      {children}
    </div>
  );
}
