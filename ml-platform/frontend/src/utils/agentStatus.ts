// 智能体运行状态的人话标签：状态机内部代号（waiting_escalate 等）对业务
// 用户有歧义（"升级"像系统升级），界面统一展示为中文业务语义；原始代号
// 保留在徽章 title 与档案 code 行供排障对照。
const LABELS: Record<string, [string, string]> = {
  pending: ["排队中", "Queued"],
  running: ["运行中", "Running"],
  waiting_guidance: ["等待引导确认", "Awaiting guidance"],
  waiting_escalate: ["未达标 · 待人工决策", "Below gates · needs decision"],
  accepted: ["验收通过", "Accepted"],
  superseded: ["已被新版取代", "Superseded"],
  cancelled: ["已取消", "Cancelled"],
};

export function agentStatusLabel(status: string, zh: boolean): string {
  const pair = LABELS[status];
  return pair ? pair[zh ? 0 : 1] : status;
}
