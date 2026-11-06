import apiClient from "./client";
import type { LabelColumnDraft } from "../components/LabelSchemaEditor";

export async function createLabelSchema(projectId: string, name: string, columns: LabelColumnDraft[], purpose: "annotation" | "training" | "inference" = "annotation") {
  const response = await apiClient.post("/annotations/label-schemas", {
    project_id: projectId,
    name,
    purpose,
    // 枚举/范围约束原样落库，标注员门户据此渲染与校验；constraint_mode/isDefault
    // 是编辑器 UI 态，后端 LabelColumnCreate 为 extra="forbid"，不能发送
    columns: columns.map(({ constraint_mode: _mode, isDefault: _isDefault, ...column }) => column),
  });
  return response.data as { id: string; project_id: string; name: string; version: number };
}
