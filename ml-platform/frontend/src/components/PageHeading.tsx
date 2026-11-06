import type { ReactNode } from "react";
import { useI18n } from "../i18n";

/**
 * 全平台统一的页面标题：格式「板块/页面名」（如 系统管理/用户管理）。
 * 板块名与分隔符弱化为次级色，页面名为主色；所有侧栏菜单页一律通过本组件
 * 渲染标题，保证四大板块样式一致。
 *
 * 页面名优先取 i18n 的 t.nav（与侧栏菜单同一真源）；测试 mock 或未来键缺失
 * 时回退 NAV_FALLBACK（navTitleFallback.test.ts 锁定两表一致）。
 */

export const SECTIONS = {
  algo: { zh: "算法平台", en: "Algorithms" },
  agent: { zh: "智能体中心", en: "Agent Center" },
  infra: { zh: "基础设施", en: "Infrastructure" },
  admin: { zh: "系统管理", en: "Administration" },
} as const;

export type SectionId = keyof typeof SECTIONS;

/** 菜单名回退表（zh 与 AppLayout 侧栏、en 与 i18n nav 对齐；有 parity 测试锁定）。 */
export const NAV_FALLBACK: Record<string, { zh: string; en: string }> = {
  dashboard: { zh: "工作台", en: "Dashboard" },
  projects: { zh: "项目管理", en: "Projects" },
  data: { zh: "数据管理", en: "Data Management" },
  data_annotation: { zh: "数据标注", en: "Data Annotation" },
  automl: { zh: "自动建模", en: "AutoML" },
  training: { zh: "模型训练", en: "Model Training" },
  models: { zh: "模型库", en: "Model Library" },
  orchestration: { zh: "应用编排", en: "App Orchestration" },
  demo_loop: { zh: "闭环自动化", en: "Closed-Loop Automation" },
  api_market: { zh: "API市场", en: "API Market" },
  prompt_templates: { zh: "提示词模板", en: "Prompt Templates" },
  chat: { zh: "AI对话", en: "AI Chat" },
  knowledge_center: { zh: "知识中心", en: "Knowledge Center" },
  kubernetes: { zh: "Kubernetes 集群", en: "Kubernetes Clusters" },
  cluster_governance: { zh: "集群治理", en: "Cluster Governance" },
  job_runs: { zh: "作业运行", en: "Job Runs" },
  notebooks: { zh: "Notebook 会话", en: "Notebook Sessions" },
  images: { zh: "镜像目录", en: "Image Catalog" },
  monitor: { zh: "资源监控", en: "Resource Monitor" },
  compute: { zh: "计算资源", en: "Compute Resources" },
  users: { zh: "用户管理", en: "User Management" },
  announcements: { zh: "公告管理", en: "Notices" },
  audit: { zh: "审计日志", en: "Audit log" },
  settings: { zh: "平台状态", en: "Platform Status" },
  llm_gateway: { zh: "大模型管理", en: "LLM Management" },
  llm_usage: { zh: "Tokens 用量", en: "Token usage" },
};

export function navTitle(t: unknown, key: string, zh: boolean): string {
  const fromI18n = (t as { nav?: Record<string, unknown> } | undefined)?.nav?.[key];
  if (typeof fromI18n === "string" && fromI18n) return fromI18n;
  const fallback = NAV_FALLBACK[key];
  if (!fallback) return key;
  return zh ? fallback.zh : fallback.en;
}

export default function PageHeading({
  section,
  title,
  navKey,
  desc,
  actions,
  testId,
}: {
  section: SectionId;
  /** 页面名静态内容；与 navKey 二选一，navKey 优先（菜单名真源）。 */
  title?: ReactNode;
  /** 侧栏菜单键：页面名自动取 t.nav[navKey]（缺失回退 NAV_FALLBACK）。 */
  navKey?: string;
  desc?: ReactNode;
  actions?: ReactNode;
  testId?: string;
}) {
  const { t, lang } = useI18n();
  // 测试的 i18n mock 可能不带 lang：缺省按中文（与 LangContext 默认一致）。
  const zh = (lang ?? "zh") === "zh";
  const resolvedTitle = navKey ? navTitle(t, navKey, zh) : title;
  return (
    <div className="v2-pagehead" data-testid={testId}>
      <div>
        <h2 className="v2-pt">
          <span className="v2-pt-sec">{zh ? SECTIONS[section].zh : SECTIONS[section].en}</span>
          <span className="v2-pt-sep">/</span>
          <span>{resolvedTitle}</span>
        </h2>
        {desc ? <p className="v2-pdesc">{desc}</p> : null}
      </div>
      {actions ? <div className="v2-pagehead-actions">{actions}</div> : null}
    </div>
  );
}
