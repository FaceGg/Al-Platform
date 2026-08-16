export function isVisualizationResultNode(
  node: any,
  status?: string,
  operators: any[] = [],
): boolean {
  if (!node || status !== "completed") return false;
  const operator = operators.find((candidate) => candidate.id === node.data?.operatorId);
  return (node.data?.category || operator?.category) === "visualization";
}
