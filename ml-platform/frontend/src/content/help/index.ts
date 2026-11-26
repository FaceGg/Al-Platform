/** 帮助中心内容注册表（补齐路线第一批 B1-15，技术方案 §6）。
 *
 * 每个新页面与其帮助章同批交付（§6 合同第 11 条）：navKeys 把路由前缀
 * 映射到章节，顶栏「帮助」按钮携带当前 pathname，帮助中心打开时定位。
 * 手册章节整册导入（评审确认点 4：整册粒度）；marked 渲染先例 DemoLoopPage。
 */
import closedLoopMd from "./closed-loop-demo.md?raw";
import deployMd from "./agent-oneclick-deploy.md?raw";
import e2eMd from "./agent-e2e.md?raw";
import platformMd from "./platform-overview.md?raw";
import qualityScenesMd from "./quality-scenes.md?raw";
import qualityStationsMd from "./quality-stations.md?raw";
import qualityRecordsMd from "./quality-production-records.md?raw";
import qualityAlertsMd from "./quality-alerts.md?raw";
import qualityDispositionMd from "./quality-disposition.md?raw";
import qualitySopsMd from "./quality-sops.md?raw";
import modelEvidenceMd from "./model-evidence.md?raw";
import qualityDashboardMd from "./quality-dashboard.md?raw";
import qualityMonitorMd from "./quality-monitor.md?raw";
import qualityTrendsMd from "./quality-trends.md?raw";
import qualitySpcMd from "./quality-spc.md?raw";
import driftMonitorMd from "./drift-monitor.md?raw";
import approvalCenterMd from "./approval-center.md?raw";
import agentActionAuditMd from "./agent-action-audit.md?raw";

export interface HelpChapter {
  id: string;
  titleZh: string;
  titleEn: string;
  order: number;
  md: string;
  /** 命中这些 pathname 前缀时，顶栏「本页帮助」定位到本章。 */
  navPrefixes?: string[];
}

export const HELP_CHAPTERS: HelpChapter[] = [
  {
    id: "platform-overview",
    titleZh: "平台说明",
    titleEn: "Platform overview",
    order: 1,
    md: platformMd,
  },
  {
    id: "quality-scenes",
    titleZh: "场景管理",
    titleEn: "Quality scenes",
    order: 2,
    md: qualityScenesMd,
    navPrefixes: ["/quality/scenes"],
  },
  {
    id: "quality-stations",
    titleZh: "工位与设备",
    titleEn: "Stations & devices",
    order: 3,
    md: qualityStationsMd,
    navPrefixes: ["/quality/stations"],
  },
  {
    id: "quality-production-records",
    titleZh: "生产记录",
    titleEn: "Production records",
    order: 4,
    md: qualityRecordsMd,
    navPrefixes: ["/quality/production-records"],
  },
  {
    id: "quality-alerts",
    titleZh: "预警中心",
    titleEn: "Alert center",
    order: 8,
    md: qualityAlertsMd,
    navPrefixes: ["/quality/alerts"],
  },
  {
    id: "quality-disposition",
    titleZh: "处置工作台",
    titleEn: "Disposition workbench",
    order: 9,
    md: qualityDispositionMd,
    navPrefixes: ["/quality/disposition"],
  },
  {
    id: "quality-sops",
    titleZh: "SOP 维护",
    titleEn: "SOP maintenance",
    order: 10,
    md: qualitySopsMd,
    navPrefixes: ["/quality/sops"],
  },
  {
    id: "model-evidence",
    titleZh: "模型库 · 闭环证据总览",
    titleEn: "Model library · closed-loop evidence",
    order: 11,
    md: modelEvidenceMd,
    navPrefixes: ["/models"],
  },
  {
    id: "quality-dashboard",
    titleZh: "质量驾驶舱",
    titleEn: "Quality cockpit",
    order: 12,
    md: qualityDashboardMd,
    navPrefixes: ["/quality/dashboard"],
  },
  {
    id: "quality-monitor",
    titleZh: "实时生产监控",
    titleEn: "Realtime monitoring",
    order: 13,
    md: qualityMonitorMd,
    navPrefixes: ["/quality/monitor"],
  },
  {
    id: "quality-trends",
    titleZh: "趋势与帕累托",
    titleEn: "Trends & Pareto",
    order: 14,
    md: qualityTrendsMd,
    navPrefixes: ["/quality/trends"],
  },
  {
    id: "quality-spc",
    titleZh: "SPC 过程控制",
    titleEn: "SPC control",
    order: 15,
    md: qualitySpcMd,
    navPrefixes: ["/quality/spc"],
  },
  {
    id: "drift-monitor",
    titleZh: "漂移监控",
    titleEn: "Drift monitoring",
    order: 16,
    md: driftMonitorMd,
    navPrefixes: ["/algo/drift"],
  },
  {
    id: "approval-center",
    titleZh: "审批中心",
    titleEn: "Approval center",
    order: 17,
    md: approvalCenterMd,
    navPrefixes: ["/approvals"],
  },
  {
    id: "agent-action-audit",
    titleZh: "动作审计",
    titleEn: "Agent action audit",
    order: 18,
    md: agentActionAuditMd,
    navPrefixes: ["/admin/agent-audit"],
  },
  {
    id: "closed-loop-demo",
    titleZh: "闭环系统演示手册",
    titleEn: "Closed-loop demo manual",
    order: 5,
    md: closedLoopMd,
  },
  {
    id: "agent-oneclick-deploy",
    titleZh: "智能体任务一键部署手册",
    titleEn: "One-click deployment manual",
    order: 6,
    md: deployMd,
  },
  {
    id: "agent-e2e",
    titleZh: "智能体任务全链 E2E 手册",
    titleEn: "Full-chain E2E manual",
    order: 7,
    md: e2eMd,
  },
];

/** 本页帮助定位：按 pathname 前缀匹配（最长前缀优先）；无映射返回 undefined。 */
export function findChapterByPage(pathname: string): HelpChapter | undefined {
  const matches = HELP_CHAPTERS.filter(
    (chapter) => (chapter.navPrefixes || []).some(
      (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
    ),
  );
  return matches.sort((left, right) => {
    const leftLen = Math.max(...(left.navPrefixes || []).map((p) => p.length));
    const rightLen = Math.max(...(right.navPrefixes || []).map((p) => p.length));
    return rightLen - leftLen;
  })[0];
}
