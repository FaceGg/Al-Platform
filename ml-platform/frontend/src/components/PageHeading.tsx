import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../i18n";

/**
 * 全平台统一的页面标题：菜单页「板块 / 页面名」（如 系统管理 / 用户管理）；
 * 详情页带父级菜单「板块 / 菜单 / 详情」（如 智能体中心 / 任务列表 / 任务详情，
 * 父级可点击返回）。板块名、父级与分隔符弱化为次级色，当前页名为主色；
 * 描述行与右侧操作位可选。
 *
 * 板块名唯一来源是 SECTIONS（顶栏也读它）；页面名优先取 i18n 的 t.nav（与侧栏
 * 菜单同一真源），测试 mock 或键缺失时回退 NAV_FALLBACK（PageHeading.test.tsx
 * 锁定两表一致）。
 */

export const SECTIONS = {
  portal: { zh: "首页门户", en: "Portal" },
  algo: { zh: "算法平台", en: "Algorithms" },
  agent: { zh: "智能体中心", en: "Agent Center" },
  infra: { zh: "基础设施", en: "Infrastructure" },
  admin: { zh: "系统管理", en: "Administration" },
} as const;

export type SectionId = keyof typeof SECTIONS;

/** 菜单名回退表（与 i18n nav 中英文逐键一致；有 parity 测试锁定）。 */
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
  algorithms: { zh: "算法目录", en: "Algorithms" },
  agent_new: { zh: "新建任务", en: "New task" },
  agent_tasks: { zh: "任务列表", en: "Jobs" },
  agent_recipes: { zh: "配方库", en: "Recipes" },
  knowledge_center: { zh: "知识中心", en: "Knowledge Center" },
  prompt_templates: { zh: "提示词模板", en: "Prompt Templates" },
  chat: { zh: "AI对话", en: "AI Chat" },
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

export function sectionName(section: SectionId, zh: boolean): string {
  return zh ? SECTIONS[section].zh : SECTIONS[section].en;
}

export interface PageHeadingParent {
  /** 父级菜单键（取菜单名）；与 title 二选一。 */
  navKey?: string;
  title?: ReactNode;
  /** 点击父级返回的路由。 */
  to: string;
}

export default function PageHeading({
  section,
  title,
  navKey,
  parent,
  desc,
  actions,
  testId,
}: {
  section: SectionId;
  /** 页面名静态内容；与 navKey 二选一，navKey 优先（菜单名真源）。 */
  title?: ReactNode;
  /** 侧栏菜单键：页面名自动取 t.nav[navKey]（缺失回退 NAV_FALLBACK）。 */
  navKey?: string;
  /** 详情页的父级菜单：渲染为「板块 / 父级 / 当前页」，父级可点击返回。 */
  parent?: PageHeadingParent;
  desc?: ReactNode;
  actions?: ReactNode;
  testId?: string;
}) {
  const { t, lang } = useI18n();
  // 测试的 i18n mock 可能不带 lang：缺省按中文（与 LangContext 默认一致）。
  const zh = (lang ?? "zh") === "zh";
  const resolvedTitle = navKey ? navTitle(t, navKey, zh) : title;
  const parentTitle = parent ? (parent.navKey ? navTitle(t, parent.navKey, zh) : parent.title) : null;
  return (
    <div className="v2-pagehead" data-testid={testId}>
      <div>
        <h2 className="v2-pt">
          <span className="v2-pt-sec">{sectionName(section, zh)}</span>
          <span className="v2-pt-sep">/</span>
          {parent ? (
            <>
              <Link className="v2-pt-parent" to={parent.to}>{parentTitle}</Link>
              <span className="v2-pt-sep">/</span>
            </>
          ) : null}
          <span>{resolvedTitle}</span>
        </h2>
        {desc ? <p className="v2-pdesc">{desc}</p> : null}
      </div>
      {actions ? <div className="v2-pagehead-actions">{actions}</div> : null}
    </div>
  );
}
