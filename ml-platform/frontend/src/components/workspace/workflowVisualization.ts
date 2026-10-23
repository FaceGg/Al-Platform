/** 完成后点击节点可打开结果抽屉的算子类别：可视化算子输出图表；评估算子
 * （classification_eval_detailed 等）输出指标/每类明细/混淆矩阵图/错误分析。
 * WorkflowCanvas 的点击判定与 workflowStore 的 openNodeResult 共用本集合。 */
export const RESULT_PANEL_CATEGORIES = new Set(["visualization", "evaluation"]);

export function isVisualizationResultNode(
  node: any,
  status?: string,
  operators: any[] = [],
): boolean {
  if (!node || status !== "completed") return false;
  const operator = operators.find((candidate) => candidate.id === node.data?.operatorId);
  return RESULT_PANEL_CATEGORIES.has(node.data?.category || operator?.category);
}
